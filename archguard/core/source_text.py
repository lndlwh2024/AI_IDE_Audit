"""只解码源码用于分析，不改写原文件。"""
import codecs
import io
import tokenize


def decode_python(data):
    for bom, encoding in ((codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
                          (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16')):
        if data.startswith(bom):
            return data.decode(encoding)
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding)
