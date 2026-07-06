## llm generated tool func, created Fri May 22 07:17:44 2026
# version: 1.0.1


import base64
import contextlib
import pathlib


def toolkit_save_file(path=None, content=None, chunks=None, append=False, encoding="utf-8", mode="text"):
    """Write file with chunked content support. Use chunks list for large files."""
    try:
        if chunks:
            assembled = "".join([str(c) for c in chunks])
        elif content:
            assembled = str(content)
        else:
            return {"status": "error", "error": "Either content or chunks must be provided"}

        if mode == "b64":
            assembled = base64.b64decode(assembled).decode(encoding)

        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and not append:
            bak = target.with_suffix(target.suffix + '.bak')
            with contextlib.suppress(Exception):
                bak.write_bytes(target.read_bytes())

        if append:
            with open(target, 'a', encoding=encoding) as f:
                f.write(assembled)
        else:
            target.write_text(assembled, encoding=encoding)

        lines = assembled.count('\n')
        if assembled and not assembled.endswith('\n'):
            lines += 1

        return {
            "status": "ok",
            "path": str(target.resolve()),
            "size_bytes": len(assembled.encode(encoding)),
            "chars": len(assembled),
            "lines": lines,
            "chunks_used": len(chunks) if chunks else 1,
            "appended": append
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def meta_toolkit_save_file() -> dict:
    return {"type": "function", "function": {"name": "toolkit_save_file", "description": "Write files with automatic chunking for large content. Use 'chunks' (list of strings) for files >5KB. Each chunk under 3000 chars. Supports append and base64 mode. For small files use 'content' parameter.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Target file path"}, "content": {"type": "string", "description": "[small files] Direct content string"}, "chunks": {"type": "array", "items": {"type": "string"}, "description": "[large files] Content chunks, joined automatically"}, "append": {"type": "boolean", "description": "Append instead of overwrite"}, "encoding": {"type": "string", "description": "File encoding, default utf-8"}, "mode": {"type": "string", "enum": ["text", "b64"], "description": "text=plain, b64=chunks are base64-encoded"}}, "required": ["path"]}}}
