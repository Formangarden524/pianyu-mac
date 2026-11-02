"""Pure text, timestamp, and Notion document operations."""
def split_text(text, limit=1600):
    if limit < 1: raise ValueError('limit must be positive')
    return [text[i:i+limit] for i in range(0, len(text), limit)]


def offset_segments(segments, offset):
    return [dict(s, start=float(s['start'])+offset, end=float(s['end'])+offset) for s in segments]


def srt(segments):
    def stamp(seconds):
        ms=max(0,round(seconds*1000));sec,ms=divmod(ms,1000);minute,sec=divmod(sec,60);hour,minute=divmod(minute,60)
        return f'{hour:02}:{minute:02}:{sec:02},{ms:03}'
    return '\n\n'.join(f"{i}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text'].strip()}" for i,s in enumerate(segments,1))+'\n'


def validate_answer(response):
    text=response.get('message',{}).get('content','').strip()
    if response.get('done_reason')!='stop' or not text:
        raise ValueError('Qwen 输出为空或被截断，请重试；没有将半成品标为完成')
    return text


def notion_blocks(title, text):
    return [{'object':'block','type':'heading_2','heading_2':{'rich_text':[{'type':'text','text':{'content':title}}]}}]+[
        {'object':'block','type':'paragraph','paragraph':{'rich_text':[{'type':'text','text':{'content':p}}]}}
        for p in split_text(text,1900)]


def code_blocks(title, text):
    """Code blocks retain newlines without creating a paragraph for every line."""
    blocks=notion_blocks(title,'')
    parts=split_text(text,1900)
    for i in range(0,len(parts),8):
        blocks.append({'object':'block','type':'code','code':{'language':'plain text','rich_text':[{'type':'text','text':{'content':p}} for p in parts[i:i+8]]}})
    return blocks


def block_batches(blocks):
    import json
    batch=[];size=0
    for block in blocks:
        n=len(json.dumps(block,ensure_ascii=False).encode())
        if batch and (len(batch)>=50 or size+n>380000):yield batch;batch=[];size=0
        batch.append(block);size+=n
    if batch:yield batch
