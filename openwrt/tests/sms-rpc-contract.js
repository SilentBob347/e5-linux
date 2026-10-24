'use strict';
// Exercise the actual LuCI SMS calls against the String arguments in rpcd.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/../luci-app-t551m/htdocs/luci-static/resources/mu300/common.js','utf8');
const calls=[];
const context={rpc:{declare(spec){return (...params)=>{
  calls.push({method:spec.method,params});return Promise.resolve({});
};}}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('var callSmsList ='),source.indexOf('var callForwardGet =')),context);
context.callSmsList(2);
context.callSmsShow(1000000001);
context.callSmsDel('1000000001',true);
context.callSmsDel('1000000001',false);
context.callSmsDel('all');
const failures=[];
for(const call of calls) {
  if(!call.params.every(p=>typeof p==='string'))failures.push(call.method+': non-string argument');
}
if(calls[2].params[1]!=='1')failures.push('SIM deletion must use "1"');
if(calls[3].params[1]!=='0'||calls[4].params[1]!=='0')failures.push('local deletion must use "0"');
assert.deepStrictEqual(failures,[]);
console.log('PASS: page, message ID and explicit delete mode match rpcd String contract');
