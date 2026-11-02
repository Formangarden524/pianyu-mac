"""Versioned local edits and durable, serial knowledge-card generation."""
import hashlib,json,time,uuid
from pathlib import Path
from .pipeline import atomic_json
from .core import split_text

FIELDS={'title':'知识卡片','core':'核心观点','blind_spots':'认知盲区','misconceptions':'常见误区','boundaries':'适用边界','actions':'行动建议'}
EDITABLE={'ready','published','publish_failed','refresh_failed'}

def version(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def validate_card(data):
    if not isinstance(data,dict) or set(data)!=set(FIELDS):raise ValueError('模型卡片格式不完整，请重试')
    for key,value in data.items():
        if not isinstance(value,str) or not value.strip() or len(value)>(100 if key=='title' else 6000):raise ValueError('卡片文字为空或过长，请缩短后保存')
    if sum(map(len,data.values()))>18000:raise ValueError('卡片内容过长，请缩短后保存')
    return {k:v.strip() for k,v in data.items()}

def render_cards(content,folder,source):
    from PIL import Image,ImageDraw,ImageFont
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    font_path='/System/Library/Fonts/STHeiti Light.ttc'
    if not Path(font_path).exists():raise RuntimeError('未找到本机中文字体 STHeiti，无法导出图片')
    body=ImageFont.truetype(font_path,34);heading=ImageFont.truetype(font_path,29);title=ImageFont.truetype(font_path,48);small=ImageFont.truetype(font_path,23)
    def wrap(text,font,width=916):
        lines=[]
        for paragraph in text.split('\n'):
            line=''
            for char in paragraph:
                if line and font.getlength(line+char)>width:
                    if char in '，。；：！？、）】》”’.,;:!?)]' and len(line)>1:
                        lines.append(line[:-1]);line=line[-1:]
                    else:lines.append(line);line=''
                line+=char
            lines.append(line)
        return lines
    # Fixed height pages with generous type size; flow all content without truncation.
    blocks=[]
    for line in wrap(content['title'],title):blocks.append((line,title,70,'#213451'))
    blocks.append(('',body,22,'#213451'))
    for key,label in FIELDS.items():
        if key=='title':continue
        blocks.append((label,heading,54,'#355be8'))
        blocks.extend((line,body,54,'#34445b') for line in wrap(content[key],body))
        blocks.append(('',body,20,'#34445b'))
    pages=[];page=[];height=0
    for block in blocks:
        # Keep a section label with at least its first line.
        needed=block[2]+(54 if block[1] is heading else 0)
        if page and height+needed>1130:pages.append(page);page=[];height=0
        page.append(block);height+=block[2]
    if page:pages.append(page)
    files=[]
    for i,lines in enumerate(pages):
        image=Image.new('RGB',(1080,1440),'#f3f6fc');draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((38,38,1042,1402),radius=26,fill='white')
        draw.rounded_rectangle((80,84,90,113),radius=4,fill='#355be8');draw.text((108,80),'片语 · 知识卡片',font=small,fill='#7b8798')
        y=150
        for text,font,step,color in lines:draw.text((82,y),text,font=font,fill=color);y+=step
        draw.line((82,1310,998,1310),fill='#e7eaf0',width=2)
        footer=wrap('来源：'+source,small,780)[0]
        draw.text((82,1334),footer,font=small,fill='#7b8798');draw.text((932,1334),f'{i+1}/{len(pages)}',font=small,fill='#7b8798')
        path=folder/f'{i+1}.png';image.save(path);files.append(path)
    return files

class ContentService:
    def __init__(self,store):
        self.store=store;self.root=store.root;self.lock=store.lock
        with self.lock,self.store.db:
            self.store.db.execute('CREATE TABLE IF NOT EXISTS card_runs (id TEXT PRIMARY KEY,jid TEXT,status TEXT,source_hash TEXT,source TEXT,error TEXT,created REAL)')
    def _folder(self,jid):
        job=self.store.get(jid);return self.root/'jobs'/job['id']
    def _result(self,jid):
        p=self._folder(jid)/'result.json'
        if not p.exists():raise ValueError('任务尚未生成整理文案')
        return json.loads(p.read_text())
    def _require_editable(self,jid):
        if self.store.get(jid)['status'] not in EDITABLE:raise ValueError('任务正在处理或写入，暂不能编辑或生成卡片')
    def detail(self,jid):
        with self.lock:
            folder=self._folder(jid);p=folder/'result.json';result=json.loads(p.read_text()) if p.exists() else None
            latest=self.store.db.execute('SELECT status,error FROM card_runs WHERE jid=? ORDER BY created DESC LIMIT 1',(jid,)).fetchone()
            pointer=folder/'cards-current.json';cards=json.loads(pointer.read_text()) if pointer.exists() else {}
            if cards:
                cards={**cards,'version':version(cards),'stale':not result or cards['source_hash']!=version(result['clean'])}
            cards.update({'status':latest['status'] if latest else 'none','error':latest['error'] if latest else ''})
            return {'content_version':version(result) if result else None,'cards':cards}
    def save_clean(self,jid,text,expected):
        if not isinstance(text,str) or not text.strip() or len(text)>500000:raise ValueError('文案不能为空且不能超过50万字')
        with self.lock:
            self._require_editable(jid);data=self._result(jid)
            if version(data)!=expected:raise ValueError('文案已变化，请保留草稿并刷新后重试')
            folder=self._folder(jid);history=folder/'content-history';history.mkdir(exist_ok=True)
            atomic_json(history/(uuid.uuid4().hex+'.json'),data)
            data['clean']=text;data['manual_edit']=True;data.pop('tags',None);atomic_json(folder/'result.json',data)
            (folder/'clean.txt').write_text(text)
            # The legacy refresh flow must not overwrite manually edited clean text.
            proofread=folder/'proofread.json'
            prior=json.loads(proofread.read_text()) if proofread.exists() else {}
            atomic_json(proofread,{**prior,'manual_edit':True,'saved_at':time.time()})
            return self.detail(jid)
    def enqueue(self,jid):
        with self.lock:
            self._require_editable(jid);data=self._result(jid)
            if self.store.db.execute("SELECT 1 FROM card_runs WHERE jid=? AND status IN ('queued','running')",(jid,)).fetchone():raise ValueError('该任务的卡片已排队或正在生成')
            run=uuid.uuid4().hex
            with self.store.db:self.store.db.execute('INSERT INTO card_runs VALUES (?,?,?,?,?,?,?)',(run,jid,'queued',version(data['clean']),data['clean'],'',time.time()))
            return self.detail(jid)
    def pending(self):
        with self.lock:return self.store.db.execute("SELECT count(*) FROM card_runs WHERE status IN ('queued','running')").fetchone()[0]
    def recover(self):
        with self.lock,self.store.db:self.store.db.execute("UPDATE card_runs SET status='failed',error='服务中断，旧卡片已保留，可重新生成' WHERE status='running'")
    def run_next(self,chat):
        with self.lock:
            row=self.store.db.execute("SELECT * FROM card_runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:return False
            row=dict(row)
            with self.store.db:self.store.db.execute("UPDATE card_runs SET status='running' WHERE id=?",(row['id'],))
        try:
            text=row['source']
            if len(text)>4500:
                text='\n'.join(chat(chunk,'summary') for chunk in split_text(text,limit=3500))
                for _ in range(12):
                    if len(text)<=4500:break
                    reduced='\n'.join(chat(chunk,'summary') for chunk in split_text(text,limit=3500))
                    if len(reduced)>=len(text):raise ValueError('长文案摘要未收敛，未截断原文，请稍后重试')
                    text=reduced
                if len(text)>4500:raise ValueError('长文案摘要层级超出限制')
            answer=chat(text,'card').strip()
            if answer.startswith('```'):answer=answer.split('\n',1)[1].rsplit('```',1)[0].strip()
            content=validate_card(json.loads(answer))
            # Absence of evidence never establishes blanket non-applicability.
            if '其他场景不适用' in content['boundaries'] and '其他场景不适用' not in row['source']:
                content['boundaries']='材料仅描述当前场景，其他场景的适用性未说明。'
            self._save_generation(row['jid'],content,row['source_hash'],row['id'])
            with self.lock,self.store.db:self.store.db.execute("UPDATE card_runs SET status='ready' WHERE id=?",(row['id'],))
        except Exception:
            with self.lock,self.store.db:self.store.db.execute("UPDATE card_runs SET status='failed',error='本地知识卡片生成失败：请检查模型服务或输出格式后重试；旧卡片已保留' WHERE id=?",(row['id'],))
        return True
    def _save_generation(self,jid,content,source_hash,generation=None):
        generation=generation or uuid.uuid4().hex;folder=self._folder(jid);out=folder/'cards'/generation
        files=render_cards(content,out,self.store.get(jid)['name'])
        card={'generation':generation,'content':content,'source_hash':source_hash,'pages':len(files)}
        atomic_json(out/'card.json',card)
        with self.lock:atomic_json(folder/'cards-current.json',card)
    def save_card(self,jid,content,expected):
        content=validate_card(content)
        with self.lock:
            self._require_editable(jid);d=self.detail(jid)['cards']
            if not d.get('generation') or d.get('version')!=expected:raise ValueError('卡片已变化，请保留草稿并刷新后重试')
            if d['status'] in ('queued','running'):raise ValueError('卡片正在生成，请完成后编辑')
            self._save_generation(jid,content,d['source_hash'])
            return self.detail(jid)
