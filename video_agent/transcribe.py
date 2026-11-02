"""Short-lived Metal ASR process; process exit releases all model allocations."""
import json,sys
from pathlib import Path

def main():
    import mlx_whisper
    result=mlx_whisper.transcribe(sys.argv[1],path_or_hf_repo=sys.argv[3],verbose=False,condition_on_previous_text=False)
    segments=[{'start':s['start'],'end':s['end'],'text':s['text']} for s in result.get('segments',[]) if s['text'].strip()]
    target=Path(sys.argv[2]);tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(segments,ensure_ascii=False));tmp.replace(target)
if __name__=='__main__':main()
