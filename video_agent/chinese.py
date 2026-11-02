"""Deterministic local Traditional-to-Simplified conversion."""
from opencc import OpenCC
_converter=OpenCC('t2s')
def simplified(text):
    return _converter.convert(text)
def simplified_result(result):
    if result is None:return None
    result=dict(result)
    for key in ('original','clean','summary','keywords'):
        if isinstance(result.get(key),str):result[key]=simplified(result[key])
    if 'segments' in result:
        result['segments']=[{**s,'text':simplified(s['text'])} for s in result['segments']]
    return result
