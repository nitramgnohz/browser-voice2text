class Voice2TextProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(1600);
    this.position = 0;
    this.flushed = false;
    this.port.onmessage = ({data}) => {
      if (data.type === 'FLUSH') {
        this.flushed = true;
        this.emit();
        this.port.postMessage({type:'FLUSHED'});
      }
    };
  }
  emit() {
    if (!this.position) return;
    const pcm = this.buffer.slice(0,this.position);
    this.port.postMessage({type:'AUDIO',pcm},[pcm.buffer]);
    this.position = 0;
  }
  process(inputs) {
    if (this.flushed) return true;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i=0; i<channels[0].length; i++) {
      let value=0;
      for (const channel of channels) value += channel[i] || 0;
      value=Math.max(-1,Math.min(1,value/channels.length));
      this.buffer[this.position++]=Math.round(value * (value < 0 ? 32768 : 32767));
      if (this.position === this.buffer.length) this.emit();
    }
    return true;
  }
}
registerProcessor('voice2text-audio',Voice2TextProcessor);
