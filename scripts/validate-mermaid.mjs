import {JSDOM} from 'jsdom';
let input='';for await(const chunk of process.stdin)input+=chunk;
const dom=new JSDOM('<!doctype html><html><body></body></html>');
globalThis.window=dom.window;globalThis.document=dom.window.document;
const {default:mermaid}=await import('mermaid');
mermaid.initialize({startOnLoad:false,securityLevel:'strict'});
const results=[];
for(const diagram of JSON.parse(input)){
 try{await mermaid.parse(diagram.source);results.push({name:diagram.name,status:'passed'})}
 catch(error){results.push({name:diagram.name,status:'failed',detail:String(error.message||error).slice(0,600)})}
}
process.stdout.write(JSON.stringify(results));
