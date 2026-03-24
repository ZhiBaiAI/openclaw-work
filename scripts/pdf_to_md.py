#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import math
import re
import statistics
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union


OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
REF_RE = re.compile(rb"(\d+)\s+0\s+R")
NUMBER_RE = re.compile(rb"^[+-]?(?:\d+\.\d+|\d+|\.\d+)$")
DELIMS = b"()<>[]{}/%\x00\t\n\f\r "


class PdfParseError(RuntimeError):
    pass


class PdfName(str):
    pass


@dataclass
class PdfString:
    data: bytes


@dataclass
class PdfHexString:
    data: bytes


@dataclass
class PdfDict:
    raw: bytes


@dataclass
class DecodedText:
    text: str
    codes: List[bytes]


@dataclass
class FontInfo:
    name: str
    widths: Dict[int, float] = field(default_factory=dict)
    default_width: float = 1000.0
    code_map: Dict[bytes, str] = field(default_factory=dict)
    code_lengths: List[int] = field(default_factory=lambda: [1])

    def decode_bytes(self, data: bytes) -> DecodedText:
        if not data:
            return DecodedText("", [])

        text_parts: List[str] = []
        codes: List[bytes] = []
        i = 0
        lengths = self.code_lengths or [1]
        while i < len(data):
            matched = False
            for length in lengths:
                if i + length > len(data):
                    continue
                code = data[i : i + length]
                if code in self.code_map:
                    text_parts.append(self.code_map[code])
                    codes.append(code)
                    i += length
                    matched = True
                    break
            if matched:
                continue

            code = data[i : i + 1]
            if code in self.code_map:
                text_parts.append(self.code_map[code])
            else:
                text_parts.append(code.decode("latin1", "ignore"))
            codes.append(code)
            i += 1

        return DecodedText("".join(text_parts), codes)

    def text_advance(self, codes: Sequence[bytes], font_size: float) -> float:
        if not codes or not font_size:
            return 0.0

        total_width = 0.0
        for code in codes:
            if len(code) == 1:
                total_width += self.widths.get(code[0], self.default_width)
            else:
                total_width += self.default_width
        return total_width / 1000.0 * font_size


@dataclass
class TextChunk:
    text: str
    x: float
    y: float
    font_size: float
    seq: int


@dataclass
class Line:
    text: str
    x: float
    y: float
    font_size: float


@dataclass
class TextState:
    font_name: Optional[str] = None
    font_size: float = 0.0
    x: float = 0.0
    y: float = 0.0
    line_x: float = 0.0
    line_y: float = 0.0
    leading: float = 0.0
    actual_text_stack: List[Tuple[str, bool]] = field(default_factory=list)

    def set_position(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self.line_x = x
        self.line_y = y

    def move_position(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        self.line_x = self.x
        self.line_y = self.y

    def next_line(self) -> None:
        self.x = self.line_x
        self.y -= self.leading
        self.line_x = self.x
        self.line_y = self.y

    def consume_actual_text(self) -> Optional[str]:
        if not self.actual_text_stack:
            return None
        text, used = self.actual_text_stack[-1]
        if used:
            return None
        self.actual_text_stack[-1] = (text, True)
        return text


class PdfObjectStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        self.objects: Dict[int, bytes] = {
            int(obj_num): body for obj_num, _gen, body in OBJ_RE.findall(self.data)
        }
        if not self.objects:
            raise PdfParseError(f"no PDF objects found in {path}")

    def get(self, obj_id: int) -> bytes:
        try:
            return self.objects[obj_id]
        except KeyError as exc:
            raise PdfParseError(f"missing object {obj_id} in {self.path}") from exc

    def get_stream(self, obj_id: int) -> bytes:
        body = self.get(obj_id)
        head, raw = split_stream_object(body, self)
        filters = parse_filters(head)
        data = raw
        for flt in filters:
            if flt == "FlateDecode":
                data = zlib.decompress(data)
            elif flt == "ASCII85Decode":
                data = base64.a85decode(data, adobe=True)
            else:
                raise PdfParseError(f"unsupported filter {flt} in object {obj_id}")
        return data

    def find_catalog_id(self) -> int:
        for obj_id, body in self.objects.items():
            if b"/Type /Catalog" in body:
                return obj_id
        raise PdfParseError(f"catalog not found in {self.path}")

    def page_ids(self) -> List[int]:
        catalog = self.get(self.find_catalog_id())
        pages_ref = find_single_ref(catalog, b"/Pages")
        if pages_ref is None:
            raise PdfParseError(f"page tree root not found in {self.path}")
        out: List[int] = []
        self._walk_pages(pages_ref, out)
        return out

    def _walk_pages(self, obj_id: int, out: List[int]) -> None:
        body = self.get(obj_id)
        if b"/Type /Page" in body and b"/Type /Pages" not in body:
            out.append(obj_id)
            return
        kids = extract_array_after(body, b"/Kids")
        if not kids:
            return
        for kid in parse_refs_in_bytes(kids):
            self._walk_pages(kid, out)

    def get_page_resources(self, page_id: int) -> bytes:
        current_id = page_id
        while current_id:
            body = self.get(current_id)
            found = extract_value_after(body, b"/Resources")
            if found is not None:
                return resolve_object_or_inline(found, self)
            parent = find_single_ref(body, b"/Parent")
            if parent is None:
                break
            current_id = parent
        return b""

    def get_page_contents(self, page_id: int) -> List[int]:
        body = self.get(page_id)
        contents = extract_value_after(body, b"/Contents")
        if contents is None:
            return []
        if isinstance(contents, int):
            return [contents]
        if isinstance(contents, bytes):
            return parse_refs_in_bytes(contents)
        return []


def split_stream_object(body: bytes, store: Optional[PdfObjectStore] = None) -> Tuple[bytes, bytes]:
    if b"stream" not in body:
        raise PdfParseError("stream object missing stream marker")
    stream_pos = body.index(b"stream")
    head = body[:stream_pos]
    raw_start = stream_pos + len(b"stream")
    if body[raw_start : raw_start + 2] == b"\r\n":
        raw_start += 2
    elif body[raw_start : raw_start + 1] in {b"\r", b"\n"}:
        raw_start += 1

    length = resolve_stream_length(head, store)
    if length is not None:
        raw = body[raw_start : raw_start + length]
    else:
        tail = body[raw_start:]
        raw = tail.split(b"endstream", 1)[0].rstrip(b"\r\n")
    return head, raw


def parse_filters(head: bytes) -> List[str]:
    match = re.search(rb"/Filter\s*(\[[^\]]+\]|/[A-Za-z0-9]+)", head, re.S)
    if not match:
        return []
    raw = match.group(1).strip()
    if raw.startswith(b"["):
        return [item.decode("ascii", "ignore") for item in re.findall(rb"/([A-Za-z0-9]+)", raw)]
    return [raw[1:].decode("ascii", "ignore")]


def resolve_stream_length(head: bytes, store: Optional[PdfObjectStore]) -> Optional[int]:
    direct = re.search(rb"/Length\s+(\d+)\b", head)
    if direct:
        return int(direct.group(1))
    ref = re.search(rb"/Length\s+(\d+)\s+0\s+R", head)
    if ref and store is not None:
        ref_body = store.get(int(ref.group(1)))
        num = re.search(rb"(\d+)", ref_body)
        if num:
            return int(num.group(1))
    return None


def parse_refs_in_bytes(data: bytes) -> List[int]:
    return [int(item) for item in re.findall(rb"(\d+)\s+0\s+R", data)]


def find_single_ref(body: bytes, key: bytes) -> Optional[int]:
    match = re.search(re.escape(key) + rb"\s+(\d+)\s+0\s+R", body)
    if match:
        return int(match.group(1))
    return None


def extract_balanced(data: bytes, start: int, open_token: bytes, close_token: bytes) -> Tuple[bytes, int]:
    depth = 0
    i = start
    length = len(data)
    while i < length:
        if data.startswith(open_token, i):
            depth += 1
            i += len(open_token)
            continue
        if data.startswith(close_token, i):
            depth -= 1
            i += len(close_token)
            if depth == 0:
                return data[start:i], i
            continue
        i += 1
    raise PdfParseError("unterminated balanced token")


def skip_ws(data: bytes, i: int) -> int:
    while i < len(data):
        byte = data[i]
        if byte in b" \t\r\n\f\x00":
            i += 1
            continue
        if byte == 0x25:
            while i < len(data) and data[i] not in b"\r\n":
                i += 1
            continue
        break
    return i


def extract_value_after(body: bytes, key: bytes) -> Optional[Union[int, bytes]]:
    pos = body.find(key)
    if pos < 0:
        return None
    i = skip_ws(body, pos + len(key))
    if i >= len(body):
        return None
    if body.startswith(b"<<", i):
        raw, _ = extract_balanced(body, i, b"<<", b">>")
        return raw
    if body[i : i + 1] == b"[":
        raw, _ = extract_balanced(body, i, b"[", b"]")
        return raw
    match = re.match(rb"(\d+)\s+0\s+R", body[i:])
    if match:
        return int(match.group(1))
    end = i
    while end < len(body) and body[end : end + 1] not in b"/<[(\r\n\t ":
        end += 1
    return body[i:end]


def extract_array_after(body: bytes, key: bytes) -> Optional[bytes]:
    value = extract_value_after(body, key)
    if isinstance(value, bytes) and value.startswith(b"["):
        return value
    return None


def resolve_object_or_inline(value: Union[int, bytes], store: PdfObjectStore) -> bytes:
    if isinstance(value, int):
        return store.get(value)
    return value


def parse_font_resources(resources: bytes, store: PdfObjectStore) -> Dict[str, int]:
    font_value = extract_value_after(resources, b"/Font")
    if font_value is None:
        return {}
    font_dict = resolve_object_or_inline(font_value, store)
    return {
        name.decode("ascii", "ignore"): int(obj_id)
        for name, obj_id in re.findall(rb"/([A-Za-z0-9_.-]+)\s+(\d+)\s+0\s+R", font_dict)
    }


def parse_xobject_resources(resources: bytes, store: PdfObjectStore) -> Dict[str, int]:
    xobj_value = extract_value_after(resources, b"/XObject")
    if xobj_value is None:
        return {}
    xobj_dict = resolve_object_or_inline(xobj_value, store)
    return {
        name.decode("ascii", "ignore"): int(obj_id)
        for name, obj_id in re.findall(rb"/([A-Za-z0-9_.-]+)\s+(\d+)\s+0\s+R", xobj_dict)
    }


def parse_widths(font_body: bytes) -> Tuple[Dict[int, float], float]:
    widths: Dict[int, float] = {}
    first_char_match = re.search(rb"/FirstChar\s+(\d+)", font_body)
    widths_match = re.search(rb"/Widths\s*\[(.*?)\]", font_body, re.S)
    if first_char_match and widths_match:
        first_char = int(first_char_match.group(1))
        parts = re.findall(rb"[+-]?(?:\d+\.\d+|\d+|\.\d+)", widths_match.group(1))
        for idx, raw in enumerate(parts):
            widths[first_char + idx] = float(raw)
    default_width = statistics.mean(widths.values()) if widths else 1000.0
    return widths, default_width


def decode_unicode_hex(hex_bytes: bytes) -> str:
    raw = bytes.fromhex(hex_bytes.decode("ascii"))
    if raw.startswith(b"\xfe\xff") or raw.startswith(b"\xff\xfe"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if len(raw) % 2 == 0:
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1", "ignore")


def increment_text(text: str, amount: int) -> str:
    if len(text) == 1:
        return chr(ord(text) + amount)
    return text


def parse_tounicode(stream: bytes) -> Tuple[Dict[bytes, str], List[int]]:
    code_map: Dict[bytes, str] = {}
    code_lengths = set()

    for section in re.finditer(rb"(\d+)\s+begincodespacerange(.*?)endcodespacerange", stream, re.S):
        for start_hex, _end_hex in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", section.group(2)):
            code_lengths.add(len(start_hex) // 2)

    for section in re.finditer(rb"(\d+)\s+beginbfchar(.*?)endbfchar", stream, re.S):
        for src, dest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", section.group(2)):
            code_map[bytes.fromhex(src.decode("ascii"))] = decode_unicode_hex(dest)

    for section in re.finditer(rb"(\d+)\s+beginbfrange(.*?)endbfrange", stream, re.S):
        block = section.group(2)
        for src_start, src_end, dest in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[^>]+>|\[[^\]]+\])",
            block,
            re.S,
        ):
            start_bytes = bytes.fromhex(src_start.decode("ascii"))
            end_bytes = bytes.fromhex(src_end.decode("ascii"))
            start_int = int.from_bytes(start_bytes, "big")
            end_int = int.from_bytes(end_bytes, "big")
            width = len(start_bytes)
            code_lengths.add(width)

            if dest.startswith(b"<"):
                dest_text = decode_unicode_hex(dest[1:-1])
                for offset, src_int in enumerate(range(start_int, end_int + 1)):
                    code_map[src_int.to_bytes(width, "big")] = increment_text(dest_text, offset)
                continue

            items = re.findall(rb"<([0-9A-Fa-f]+)>", dest)
            for offset, src_int in enumerate(range(start_int, end_int + 1)):
                if offset >= len(items):
                    break
                code_map[src_int.to_bytes(width, "big")] = decode_unicode_hex(items[offset])

    if not code_lengths and code_map:
        code_lengths = {len(key) for key in code_map}
    return code_map, sorted(code_lengths or {1}, reverse=True)


def parse_font(store: PdfObjectStore, font_name: str, obj_id: int) -> FontInfo:
    body = store.get(obj_id)
    widths, default_width = parse_widths(body)
    code_map: Dict[bytes, str] = {}
    code_lengths = [1]

    to_unicode_ref = find_single_ref(body, b"/ToUnicode")
    if to_unicode_ref is not None:
        cmap = store.get_stream(to_unicode_ref)
        code_map, code_lengths = parse_tounicode(cmap)

    return FontInfo(
        name=font_name,
        widths=widths,
        default_width=default_width,
        code_map=code_map,
        code_lengths=code_lengths,
    )


def read_literal_string(data: bytes, i: int) -> Tuple[PdfString, int]:
    assert data[i : i + 1] == b"("
    i += 1
    depth = 1
    out = bytearray()
    while i < len(data):
        byte = data[i]
        if byte == 0x5C:
            i += 1
            if i >= len(data):
                break
            esc = data[i]
            if esc in b"nrtbf":
                out.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}[esc])
                i += 1
                continue
            if esc in b"()\\":
                out.append(esc)
                i += 1
                continue
            if esc in b"\r\n":
                if esc == 13 and i + 1 < len(data) and data[i + 1] == 10:
                    i += 2
                else:
                    i += 1
                continue
            if 48 <= esc <= 55:
                oct_digits = bytes([esc])
                i += 1
                while i < len(data) and len(oct_digits) < 3 and 48 <= data[i] <= 55:
                    oct_digits += bytes([data[i]])
                    i += 1
                out.append(int(oct_digits, 8))
                continue
            out.append(esc)
            i += 1
            continue
        if byte == 0x28:
            depth += 1
            out.append(byte)
            i += 1
            continue
        if byte == 0x29:
            depth -= 1
            if depth == 0:
                return PdfString(bytes(out)), i + 1
            out.append(byte)
            i += 1
            continue
        out.append(byte)
        i += 1
    raise PdfParseError("unterminated literal string")


def read_hex_string(data: bytes, i: int) -> Tuple[PdfHexString, int]:
    assert data[i : i + 1] == b"<" and data[i : i + 2] != b"<<"
    end = data.find(b">", i + 1)
    if end < 0:
        raise PdfParseError("unterminated hex string")
    raw = re.sub(rb"\s+", b"", data[i + 1 : end])
    if len(raw) % 2:
        raw += b"0"
    return PdfHexString(bytes.fromhex(raw.decode("ascii"))), end + 1


def read_dict(data: bytes, i: int) -> Tuple[PdfDict, int]:
    raw, end = extract_balanced(data, i, b"<<", b">>")
    return PdfDict(raw), end


Token = Union[float, str, PdfName, PdfString, PdfHexString, PdfDict, list]


def read_value(data: bytes, i: int) -> Tuple[Token, int]:
    i = skip_ws(data, i)
    if i >= len(data):
        raise EOFError
    if data.startswith(b"<<", i):
        return read_dict(data, i)
    if data[i : i + 1] == b"[":
        return read_array(data, i)
    if data[i : i + 1] == b"(":
        return read_literal_string(data, i)
    if data[i : i + 1] == b"<":
        return read_hex_string(data, i)
    if data[i : i + 1] == b"/":
        end = i + 1
        while end < len(data) and data[end] not in DELIMS:
            end += 1
        return PdfName(data[i + 1 : end].decode("latin1")), end

    end = i
    while end < len(data) and data[end] not in DELIMS:
        end += 1
    raw = data[i:end]
    if NUMBER_RE.match(raw):
        return float(raw), end
    return raw.decode("latin1"), end


def read_array(data: bytes, i: int) -> Tuple[list, int]:
    assert data[i : i + 1] == b"["
    i += 1
    items: list = []
    while True:
        i = skip_ws(data, i)
        if i >= len(data):
            raise PdfParseError("unterminated array")
        if data[i : i + 1] == b"]":
            return items, i + 1
        item, i = read_value(data, i)
        items.append(item)


def tokenize(data: bytes) -> Iterator[Token]:
    i = 0
    while True:
        i = skip_ws(data, i)
        if i >= len(data):
            return
        token, i = read_value(data, i)
        yield token


def parse_actual_text(dict_token: PdfDict) -> Optional[str]:
    match = re.search(rb"/ActualText\s*(<[^>]+>|\((?:\\.|[^\\)])*\))", dict_token.raw, re.S)
    if not match:
        return None
    raw = match.group(1)
    if raw.startswith(b"<"):
        return decode_unicode_hex(raw[1:-1])
    literal, _ = read_literal_string(raw, 0)
    try:
        return literal.data.decode("utf-16-be")
    except UnicodeDecodeError:
        return literal.data.decode("latin1", "ignore")


def decode_text_operand(token: Union[PdfString, PdfHexString]) -> bytes:
    if isinstance(token, PdfString):
        return token.data
    return token.data


def show_text(
    token: Union[PdfString, PdfHexString],
    state: TextState,
    fonts: Dict[str, FontInfo],
    chunks: List[TextChunk],
    seq: int,
) -> int:
    if not state.font_name or state.font_name not in fonts:
        return seq
    font = fonts[state.font_name]
    decoded = font.decode_bytes(decode_text_operand(token))
    text = state.consume_actual_text() or decoded.text
    text = normalize_text(text)
    if text:
        chunks.append(TextChunk(text=text, x=state.x, y=state.y, font_size=state.font_size, seq=seq))
        seq += 1
    state.x += font.text_advance(decoded.codes, state.font_size)
    return seq


def parse_content_stream(
    data: bytes,
    fonts: Dict[str, FontInfo],
    chunks: List[TextChunk],
    xobjects: Optional[Dict[str, bytes]] = None,
    inherited_state: Optional[TextState] = None,
    seq: int = 0,
) -> int:
    state = inherited_state or TextState()
    operands: List[Token] = []
    xobjects = xobjects or {}

    for token in tokenize(data):
        if type(token) is not str:
            operands.append(token)
            continue

        op = token
        if op == "BT":
            state = TextState()
        elif op == "Tf" and len(operands) >= 2:
            font_name = operands[-2]
            font_size = operands[-1]
            if isinstance(font_name, PdfName) and isinstance(font_size, float):
                state.font_name = str(font_name)
                state.font_size = font_size
        elif op == "Tm" and len(operands) >= 6:
            nums = operands[-6:]
            if all(isinstance(item, float) for item in nums):
                e = float(nums[4])
                f = float(nums[5])
                state.set_position(e, f)
        elif op == "Td" and len(operands) >= 2:
            tx, ty = operands[-2:]
            if isinstance(tx, float) and isinstance(ty, float):
                state.move_position(tx, ty)
        elif op == "TD" and len(operands) >= 2:
            tx, ty = operands[-2:]
            if isinstance(tx, float) and isinstance(ty, float):
                state.leading = -ty
                state.move_position(tx, ty)
        elif op == "TL" and operands and isinstance(operands[-1], float):
            state.leading = float(operands[-1])
        elif op == "T*" :
            state.next_line()
        elif op == "'" and operands and isinstance(operands[-1], (PdfString, PdfHexString)):
            state.next_line()
            seq = show_text(operands[-1], state, fonts, chunks, seq)
        elif op == '"' and operands and isinstance(operands[-1], (PdfString, PdfHexString)):
            state.next_line()
            seq = show_text(operands[-1], state, fonts, chunks, seq)
        elif op == "Tj" and operands and isinstance(operands[-1], (PdfString, PdfHexString)):
            seq = show_text(operands[-1], state, fonts, chunks, seq)
        elif op == "TJ" and operands and isinstance(operands[-1], list):
            for item in operands[-1]:
                if isinstance(item, (PdfString, PdfHexString)):
                    seq = show_text(item, state, fonts, chunks, seq)
                elif isinstance(item, float):
                    state.x += -(item / 1000.0) * state.font_size
        elif op == "BDC":
            for item in reversed(operands):
                if isinstance(item, PdfDict):
                    actual_text = parse_actual_text(item)
                    if actual_text:
                        state.actual_text_stack.append((normalize_text(actual_text), False))
                    break
        elif op == "EMC":
            if state.actual_text_stack:
                state.actual_text_stack.pop()
        elif op == "Do" and operands and isinstance(operands[-1], PdfName):
            name = str(operands[-1])
            form_data = xobjects.get(name)
            if form_data:
                seq = parse_content_stream(form_data, fonts, chunks, {}, state, seq)

        operands.clear()

    return seq


def normalize_text(text: str) -> str:
    text = text.replace("\u0000", "")
    text = text.replace("\r", "")
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"[ ]{2,}", " ", text)
    text = normalize_fragmented_ascii(text)
    return text.strip()


ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def normalize_fragmented_ascii(text: str) -> str:
    if not text:
        return text

    # Collapse digit fragments: 2 0 2 6 -> 2026
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    # Collapse spaces around date/version separators: 2026 - 03 - 17 -> 2026-03-17
    text = re.sub(r"(?<=\d)\s*([:/._#-])\s*(?=\d)", r"\1", text)
    # Collapse spaces around common version prefixes: v 1.3.1 -> v1.3.1
    text = re.sub(r"\b([vV])\s+(?=\d)", r"\1", text)

    parts = text.split(" ")
    out: List[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        if not is_ascii_fragment(part):
            out.append(part)
            i += 1
            continue

        j = i
        run: List[str] = []
        while j < len(parts) and is_ascii_fragment(parts[j]):
            run.append(parts[j])
            j += 1

        if should_merge_ascii_run(run):
            out.append("".join(run))
        else:
            out.extend(run)
        i = j

    text = " ".join(filter(None, out))
    # Final cleanup for patterns like "build #5"
    text = re.sub(r"(?<=#)\s+(?=\d)", "", text)
    return text


def is_ascii_fragment(part: str) -> bool:
    if not part:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9]+", part))


def should_merge_ascii_run(run: Sequence[str]) -> bool:
    if len(run) < 2:
        return False
    if all(item.isdigit() for item in run):
        return True

    total = sum(len(item) for item in run)
    if total < 3:
        return False

    short_count = sum(1 for item in run if len(item) <= 2)
    if short_count >= len(run) - 1:
        return True

    # Handle camel-like fragments such as "Git H u b"
    if any(len(item) == 1 for item in run) and len(run) >= 3:
        return True

    return False


def build_lines(chunks: Sequence[TextChunk]) -> List[Line]:
    if not chunks:
        return []

    ordered = sorted(chunks, key=lambda item: (-item.y, item.x, item.seq))
    lines: List[List[TextChunk]] = []
    for chunk in ordered:
        if not lines:
            lines.append([chunk])
            continue
        last_line = lines[-1]
        anchor = statistics.mean(item.y for item in last_line)
        line_size = max(item.font_size for item in last_line)
        tolerance = max(2.0, min(line_size, chunk.font_size) * 0.35)
        if abs(anchor - chunk.y) <= tolerance:
            last_line.append(chunk)
        else:
            lines.append([chunk])

    result: List[Line] = []
    for line_chunks in lines:
        line_chunks.sort(key=lambda item: (item.x, item.seq))
        text_parts: List[str] = []
        prev_x: Optional[float] = None
        prev_size = 0.0
        for chunk in line_chunks:
            if not chunk.text:
                continue
            if text_parts and prev_x is not None:
                gap = chunk.x - prev_x
                if gap > max(prev_size, chunk.font_size) * 0.9 and should_insert_space(text_parts[-1], chunk.text):
                    text_parts.append(" ")
            text_parts.append(chunk.text)
            prev_x = chunk.x
            prev_size = chunk.font_size

        text = normalize_text("".join(text_parts))
        if not text:
            continue

        result.append(
            Line(
                text=text,
                x=min(item.x for item in line_chunks),
                y=statistics.mean(item.y for item in line_chunks),
                font_size=max(item.font_size for item in line_chunks),
            )
        )
    return result


def should_insert_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    last = left[-1]
    first = right[0]
    if is_cjk(last) or is_cjk(first):
        return False
    if last.isalnum() and first.isalnum():
        return True
    if last in ",.;:!?)" or first in ",.;:!?)":
        return False
    return True


def is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
    )


def detect_body_font_size(lines: Sequence[Line]) -> float:
    sizes = [round(line.font_size, 2) for line in lines if line.text]
    if not sizes:
        return 12.0
    try:
        return statistics.mode(sizes)
    except statistics.StatisticsError:
        return statistics.median(sizes)


def format_markdown(pages: Sequence[List[Line]]) -> str:
    flat_lines = [line for page in pages for line in page]
    body_size = detect_body_font_size(flat_lines)
    markdown: List[str] = []

    for page_index, page_lines in enumerate(pages, start=1):
        if not page_lines:
            continue
        page_lines = [line for line in page_lines if not is_probable_page_number(line, body_size)]
        if not page_lines:
            continue

        if markdown:
            markdown.append("")
            markdown.append(f"<!-- page {page_index} -->")
            markdown.append("")

        gaps = [
            page_lines[i].y - page_lines[i + 1].y
            for i in range(len(page_lines) - 1)
            if page_lines[i].y > page_lines[i + 1].y
        ]
        typical_gap = statistics.median(gaps) if gaps else body_size * 1.3

        previous: Optional[Line] = None
        previous_heading = False
        for line in page_lines:
            heading_level = classify_heading(line, body_size)
            if markdown and markdown[-1] != "":
                needs_blank = False
                if previous is not None:
                    vertical_gap = previous.y - line.y
                    if previous_heading or heading_level > 0:
                        needs_blank = True
                    elif abs(previous.font_size - line.font_size) > 1.5:
                        needs_blank = True
                    elif vertical_gap > typical_gap * 1.55:
                        needs_blank = True
                if needs_blank:
                    markdown.append("")

            text = line.text
            if heading_level > 0:
                text = f"{'#' * heading_level} {text}"
            markdown.append(text)
            previous = line
            previous_heading = heading_level > 0

    return "\n".join(trim_extra_blank_lines(markdown)).strip() + "\n"


def classify_heading(line: Line, body_size: float) -> int:
    text = line.text.strip()
    if not text:
        return 0
    if len(text) > 80:
        return 0
    if looks_like_list_item(text):
        return 0
    ratio = line.font_size / max(body_size, 1.0)
    if ratio >= 2.2:
        return 1
    if ratio >= 1.6:
        return 2
    if ratio >= 1.3:
        return 3
    return 0


def looks_like_list_item(text: str) -> bool:
    return bool(
        re.match(r"^([0-9]+[.)]|[-*+]|[一二三四五六七八九十]+[、.])\s*", text)
    )


def is_probable_page_number(line: Line, body_size: float) -> bool:
    text = line.text.strip()
    if not text:
        return True
    if line.font_size > body_size * 1.1:
        return False
    if re.fullmatch(r"[0-9]{1,4}", text):
        return True
    return False


def trim_extra_blank_lines(lines: Sequence[str]) -> List[str]:
    out: List[str] = []
    blank = False
    for line in lines:
        if line.strip():
            out.append(line.rstrip())
            blank = False
        elif not blank:
            out.append("")
            blank = True
    while out and not out[-1].strip():
        out.pop()
    return out


def load_form_xobjects(store: PdfObjectStore, resources: bytes) -> Dict[str, bytes]:
    forms: Dict[str, bytes] = {}
    for name, obj_id in parse_xobject_resources(resources, store).items():
        body = store.get(obj_id)
        if b"/Subtype /Form" not in body or b"stream" not in body:
            continue
        try:
            forms[name] = store.get_stream(obj_id)
        except Exception:
            continue
    return forms


def convert_pdf(path: Path, output_dir: Path) -> Path:
    store = PdfObjectStore(path)
    pages: List[List[Line]] = []

    for page_id in store.page_ids():
        resources = store.get_page_resources(page_id)
        font_refs = parse_font_resources(resources, store)
        fonts = {name: parse_font(store, name, obj_id) for name, obj_id in font_refs.items()}
        xobjects = load_form_xobjects(store, resources)

        chunks: List[TextChunk] = []
        seq = 0
        for contents_id in store.get_page_contents(page_id):
            try:
                stream_data = store.get_stream(contents_id)
            except Exception:
                continue
            seq = parse_content_stream(stream_data, fonts, chunks, xobjects, None, seq)
        pages.append(build_lines(chunks))

    markdown = format_markdown(pages)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{path.stem}.md"
    # Use UTF-8 with BOM for better compatibility with Windows editors.
    out_path.write_text(markdown, encoding="utf-8-sig")
    return out_path


def discover_pdfs(paths: Sequence[str]) -> List[Path]:
    if paths:
        return [Path(item).resolve() for item in paths]
    return sorted(Path.cwd().glob("*.pdf"))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert PDF files to rough Markdown without external dependencies.")
    parser.add_argument("pdfs", nargs="*", help="PDF files to convert. Defaults to all PDFs in the current directory.")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="converted_md",
        help="Directory for generated Markdown files. Default: converted_md",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    pdfs = discover_pdfs(args.pdfs)
    if not pdfs:
        print("No PDF files found.", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir).resolve()
    for pdf in pdfs:
        print(f"Converting {pdf.name} ...")
        try:
            out_path = convert_pdf(pdf, output_dir)
        except Exception as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            return 1
        print(f"  wrote {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
