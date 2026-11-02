class PreviewState {
  constructor(){this.selected=null;this.current=null;this.requestSeq=0;}
  select(id){this.selected=id;this.current=null;this.requestSeq++;}
  request(id){return id===this.selected?++this.requestSeq:-1;}
  accept(id,data,request=this.requestSeq){if(request!==this.requestSeq||id!==this.selected||data.job.id!==id)return false;this.current=data;return true;}
  publishId(){return this.current&&this.current.job.id===this.selected&&['ready','publish_failed','published','refresh_failed'].includes(this.current.job.status)?this.current.job.id:null;}
}
if(typeof module!=='undefined')module.exports={PreviewState};
