'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(__dirname+'/../luci-app-t551m/htdocs/luci-static/resources/mu300/common.js','utf8');
let tick,head='a',list=[],reads=0,fail=false,notifications=[],hold=null;
const context={Promise,Math,parseInt,Error,document:{hidden:false},
  window:{setInterval(fn){tick=fn;}},rpc:{declare(){return ()=>Promise.resolve({signature:head});}},
  callSmsList(){reads++;if(hold)return hold;if(fail)return Promise.reject(Error('busy'));return Promise.resolve({msgs:list});},
  notify(...args){notifications.push(args);}};
vm.createContext(context);
vm.runInContext(code.slice(code.indexOf('var callSmsHead ='),code.indexOf('\nfunction confirmBox')),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function next(){tick();await flush();}
(async()=>{
  context.watchSms();await next();assert.equal(reads,1);assert.equal(notifications.length,0);
  await next();assert.equal(reads,1,'unchanged inbox must not be downloaded');
  head='b';list=[{id:1,dir:'mt',peer:'test',preview:'test'}];await next();assert.equal(notifications.length,1);
  head='c';fail=true;await next();assert.equal(context.smsWatch.signature,'b');
  fail=false;list.push({id:2,dir:'mt'});await next();assert.equal(notifications.length,2);
  context.document.hidden=true;head='d';await next();assert.equal(reads,4);
  context.document.hidden=false;
  hold=new Promise(resolve=>{context.resolveList=resolve;});tick();await flush();let before=reads;
  tick();await flush();assert.equal(reads,before,'overlapping requests must be suppressed');
  context.resolveList({msgs:[{id:3,dir:'mo'}]});hold=null;await flush();assert.equal(notifications.length,2);
  head='empty';list=[];await next();assert.equal(context.smsWatch.seen,0);
  head='new';list=[{id:4,dir:'mt'}];await next();assert.equal(notifications.length,3);
  console.log('PASS: unchanged, baseline, both-SIM shared inbox, retry, overlap, visibility, outgoing and reset');
})().catch(e=>{console.error(e);process.exitCode=1;});
