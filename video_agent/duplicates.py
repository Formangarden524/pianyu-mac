"""Remote duplicate detection scoped to the selected Notion destination."""
import hashlib,json,re,unicodedata
from urllib.parse import urlencode
from .notion import NotionError
from .titles import clean_title


def video_digest(folder):
    cache=folder/'source-sha256.txt'
    if cache.exists():return cache.read_text().strip()
    h=hashlib.sha256()
    with (folder/'source.video').open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    digest=h.hexdigest();cache.write_text(digest);return digest


def normalize_title(value):
    return unicodedata.normalize('NFC',re.sub(r'\s*·\s*[a-fA-F0-9]{8,64}$','',value).strip()).casefold()


def same_id(a,b):return str(a).replace('-','').lower()==str(b).replace('-','').lower()


def find_duplicates(client,target,job,folder):
    digest=video_digest(folder);candidates={};cursor=None
    def add(page,title):
        if page.get('archived') or page.get('in_trash'):return
        hash_match=bool(re.search(r'·\s*'+digest[:12]+r'$',title))
        name_match=normalize_title(title)==normalize_title(job['name'][:150]) or normalize_title(clean_title(title))==normalize_title(clean_title(job['name']))
        if not (hash_match or name_match or same_id(page['id'],job.get('page_id'))):return
        candidates[page['id']]={'id':page['id'],'title':title,'url':page.get('url') or 'https://www.notion.so/'+page['id'].replace('-',''),'reason':'视频指纹相同' if hash_match else ('已关联的原记录' if same_id(page['id'],job.get('page_id')) else '视频名称相同'),'last_edited_time':page.get('last_edited_time','')}
    while True:
        if target['kind']=='data_source':
            payload={'page_size':100,'filter':{'or':[{'property':target['title_property'],'title':{'contains':job['name'][:60]}},{'property':target['title_property'],'title':{'contains':digest[:12]}},{'property':target['title_property'],'title':{'contains':clean_title(job['name'])[:60]}}]}}
            if cursor:payload['start_cursor']=cursor
            response=client.request('POST','/data_sources/'+target['id']+'/query',payload)
            for page in response.get('results',[]):
                prop=next((v for v in page.get('properties',{}).values() if v.get('type')=='title'),{})
                add(page,''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in prop.get('title',[])))
        else:
            query='?page_size=100'+('&'+urlencode({'start_cursor':cursor}) if cursor else '')
            response=client.request('GET','/blocks/'+target['id']+'/children'+query)
            for b in response.get('results',[]):
                if b['type']=='child_page':add(b,b['child_page']['title'])
        if not response.get('has_more'):break
        cursor=response['next_cursor']
    if job.get('page_id') and not any(same_id(p,job['page_id']) for p in candidates):
        try:
            page=client.request('GET','/pages/'+job['page_id']);parent=page.get('parent',{})
            parent_id=parent.get('data_source_id') if target['kind']=='data_source' else parent.get('page_id')
            if same_id(parent_id,target['id']):
                prop=next((v for v in page.get('properties',{}).values() if v.get('type')=='title'),{})
                add(page,''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in prop.get('title',[])))
        except NotionError as e:
            if getattr(e,'status_code',None)!=404:raise
    return list(candidates.values())
