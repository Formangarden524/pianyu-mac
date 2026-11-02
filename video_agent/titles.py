"""Display titles independent of original media filenames and source digests."""
import re

def clean_title(name):
    value=re.sub(r'\s*·\s*[a-fA-F0-9]{8,64}\s*$','',str(name)).strip()
    value=re.sub(r'\.(mp4|mov|mkv|webm)\s*$','',value,flags=re.I)
    value=re.sub(r'_xWT[0-9]+$','',value)
    # A hash starting a word is a topic marker; preserve language names such as C#.
    match=re.search(r'(?<![A-Za-z0-9])#\S',value)
    if match:value=value[:match.start()]
    value=value.strip(' _\t\r\n')
    return value[:150] or '视频笔记'

def title_properties(target,name):
    return {target.get('title_property','title'):{'type':'title','title':[{'type':'text','text':{'content':clean_title(name)}}]}}
