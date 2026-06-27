## llm generated tool func, created Fri May 22 07:47:11 2026
# version: 1.0.0


import base64, pathlib, logging
from tea_agent import session_ref

logger = logging.getLogger("stream_save")

def toolkit_stream_save(stream_id=None, target_path=None, append=False):
    """
    Flush STP stream buffer to disk.
    
    Args:
        stream_id: The key from [[STREAM:key=...]] marker
        target_path: Optional override for target file path
        append: If True, append to file instead of overwriting
    
    Returns:
        dict with status, path, bytes_written, etc.
    """
    try:
        sess = session_ref.get_session()
        if sess is None:
            return {"status": "error", "error": "No active session"}
        
        buffers = sess.context._stream_buffers
        if stream_id not in buffers:
            available = list(buffers.keys())
            return {
                "status": "error",
                "error": f"Stream '{stream_id}' not found in buffer",
                "available_streams": available
            }
        
        buf = buffers.pop(stream_id)  # consume the buffer
        path = target_path or buf.get('path', '')
        if not path:
            return {"status": "error", "error": "No target path specified (set in stream header or target_path arg)"}
        
        encoding = buf.get('encoding', 'raw')
        chunks = buf.get('chunks', [])
        assembled = "".join(chunks)
        
        if encoding == 'b64':
            try:
                data = base64.b64decode(assembled)
                text = data.decode('utf-8')
            except Exception as e:
                return {"status": "error", "error": f"Base64 decode failed: {e}"}
        else:
            text = assembled
        
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Backup if exists and not appending
        if target.exists() and not append:
            bak = target.with_suffix(target.suffix + '.bak')
            try:
                bak.write_bytes(target.read_bytes())
            except Exception:
                logger.exception("operation failed")

        
        if append:
            with open(target, 'a', encoding='utf-8') as f:
                f.write(text)
        else:
            target.write_text(text, encoding='utf-8')
        
        lines = text.count('\n')
        if text and not text.endswith('\n'):
            lines += 1
        
        logger.info(f"STP flushed: {stream_id} -> {target} ({len(text)} chars, {lines} lines)")
        
        return {
            "status": "ok",
            "path": str(target.resolve()),
            "chars": len(text),
            "lines": lines,
            "stream_id": stream_id,
            "encoding": encoding,
            "appended": append
        }
    except Exception as e:
        logger.error(f"Stream save failed: {e}")
        return {"status": "error", "error": str(e)}


def meta_toolkit_stream_save() -> dict:
    return {"type": "function", "function": {"name": "toolkit_stream_save", "description": "Flush a STP (Stream Tag Protocol) buffer to disk. After the model outputs [[STREAM:key=NAME:path=FILE:enc=b64]]...content...[[/STREAM]], call this with stream_id=NAME to write the captured content to FILE. Supports base64 and raw encoding. This side-channel bypasses the JSON tool-call argument size limit entirely.", "parameters": {"type": "object", "properties": {"stream_id": {"type": "string", "description": "The stream key from [[STREAM:key=...]] marker"}, "target_path": {"type": "string", "description": "Override target file path (optional, uses path from stream header if not set)"}, "append": {"type": "boolean", "description": "Append to file instead of overwriting"}}, "required": ["stream_id"]}}}
