import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {boot} from '../../apps/library/static/app.js';

const html = await readFile(new URL('../../apps/library/static/index.html',import.meta.url),'utf8');
function fixture(){return {date:'2026-09-07',cached:false,stale:false,warning:'',checked_at:'2026-09-07T10:00:00+09:00',rooms:[
 {code:'C01',group:'C',name:'<img src=x onerror=alert(1)>',minimum:1,capacity:1,state:'ok',starts:['17:00'],step_minutes:30},
 {code:'S01',group:'S',name:'제1세미나실',minimum:1,capacity:8,state:'ok',starts:['17:00'],step_minutes:30}
]};}

test('first visit fetches once; filters do not fetch; text stays text',async()=>{
 const dom=new JSDOM(html,{url:'http://localhost/'}), doc=dom.window.document, calls=[];
 const fetcher=async url=>{calls.push(url);return {ok:true,json:async()=>url==='/api/config'?{today:'2026-09-07',last_date:'2026-09-13'}:fixture()};};
 await boot(doc,fetcher,()=>({date:'2026-09-07',time:'10:00'}));
 assert.equal(calls.length,2);
 assert.equal(doc.querySelectorAll('#schedule tbody tr').length,23);
 assert.equal(doc.querySelectorAll('button.cell.available').length,2);
 assert.equal(doc.querySelectorAll('#schedule img').length,0);
 doc.querySelector('[data-group="S"]').click();
 assert.equal(calls.length,2);
 assert.equal(doc.querySelectorAll('button.cell.available').length,1);
 assert.match(doc.querySelector('#summary').textContent,/1/);
 doc.querySelector('#refresh').click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,3);
 dom.window.close();
});

test('failed new date never displays old date data under the new date',async()=>{
 const dom=new JSDOM(html,{url:'http://localhost/'}),doc=dom.window.document;
 let fail=false;
 const fetcher=async url=>({ok:!fail,json:async()=>fail?{detail:'도서관 로그인 만료'}:url==='/api/config'?{today:'2026-09-07',last_date:'2026-09-13'}:fixture()});
 await boot(doc,fetcher,()=>({date:'2026-09-07',time:'10:00'}));
 fail=true;doc.querySelector('#date').value='2026-09-08';
 doc.querySelector('#date').dispatchEvent(new dom.window.Event('change'));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(doc.querySelectorAll('#schedule button.cell.available').length,0);
 assert.match(doc.querySelector('#message').textContent,/로그인 만료/);
 assert.equal(doc.querySelector('#message').hidden,false);
 dom.window.close();
});

test('clearing the date disables navigation, sends no request and recovers with Today',async()=>{
 const dom=new JSDOM(html,{url:'http://localhost/'}),doc=dom.window.document,calls=[],errors=[];
 dom.window.addEventListener('error',event=>{errors.push(event.error);event.preventDefault();});
 const fetcher=async url=>{calls.push(url);return {ok:true,json:async()=>url==='/api/config'?{today:'2026-09-07',last_date:'2026-09-13'}:fixture()};};
 await boot(doc,fetcher,()=>({date:'2026-09-07',time:'10:00'}));
 doc.querySelector('#date').value='';
 doc.querySelector('#date').dispatchEvent(new dom.window.Event('change'));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(doc.querySelector('#next').disabled,true);
 assert.equal(doc.querySelector('#prev').disabled,true);
 doc.querySelector('#next').dispatchEvent(new dom.window.Event('click'));
 assert.deepEqual(errors,[]);
 assert.equal(calls.length,2);
 assert.equal(doc.querySelectorAll('#schedule button.cell.available').length,0);
 doc.querySelector('#today').click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(doc.querySelector('#date').value,'2026-09-07');
 assert.equal(calls.length,3);
 assert.equal(doc.querySelectorAll('#schedule button.cell.available').length,2);
 dom.window.close();
});

test('an expired app session returns the browser to login',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/'}),doc=dom.window.document,navigations=[];
 const fetcher=async()=>({status:401,ok:false,json:async()=>({detail:'도서관 로그인이 만료됐어. 다시 로그인해 줘.'})});

 await boot(doc,fetcher,()=>({date:'2026-09-08',time:'10:00'}),url=>navigations.push(url));

 assert.deepEqual(navigations,['/login']);
 assert.equal(doc.querySelectorAll('#schedule button.cell.available').length,0);
 dom.window.close();
});

test('an empty schedule 401 redirects before attempting JSON parsing',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/'}),doc=dom.window.document,navigations=[];
 const fetcher=async url=>url==='/api/config'?
  {status:200,ok:true,json:async()=>({today:'2026-09-08',last_date:'2026-09-14'})}:
  {status:401,ok:false,json:async()=>{throw new Error('synthetic JSON parse');}};

 await boot(doc,fetcher,()=>({date:'2026-09-08',time:'10:00'}),url=>navigations.push(url));

 assert.deepEqual(navigations,['/login']);
 dom.window.close();
});

test('a non-JSON schedule error shows generic text',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/'}),doc=dom.window.document;
 const fetcher=async url=>url==='/api/config'?
  {status:200,ok:true,json:async()=>({today:'2026-09-08',last_date:'2026-09-14'})}:
  {status:502,ok:false,json:async()=>{throw new Error('synthetic JSON parse');}};

 await boot(doc,fetcher,()=>({date:'2026-09-08',time:'10:00'}));

 assert.equal(doc.querySelector('#message').textContent,'조회에 실패했어.');
 dom.window.close();
});

test('header shows the masked current account and logout uses session csrf',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/'}),doc=dom.window.document,calls=[],navigations=[];
 const schedule={...fixture(),date:'2026-09-08',checked_at:'2026-09-08T10:00:00+09:00'};
 const fetcher=async(url,init={})=>{
  calls.push({url,init});
  if(url==='/api/config') return {ok:true,status:200,json:async()=>({today:'2026-09-08',last_date:'2026-09-14',csrf_token:'session-csrf',booking_enabled:true,account_label:'20****34'})};
  if(url==='/api/logout') return {ok:true,status:204,json:async()=>{throw new Error('empty response');}};
  return {ok:true,status:200,json:async()=>schedule};
 };

 await boot(doc,fetcher,()=>({date:'2026-09-08',time:'10:00'}),url=>navigations.push(url));
 assert.equal(doc.querySelector('#account-label').textContent,'20****34');
 assert.equal(doc.querySelector('a[href="/manual"]'),null);
 doc.querySelector('#logout').click();
 await new Promise(resolve=>setImmediate(resolve));

 const logout=calls.find(call=>call.url==='/api/logout');
 assert.equal(logout.init.method,'POST');
 assert.equal(logout.init.headers['X-Library-CSRF'],'session-csrf');
 assert.deepEqual(navigations,['/login']);
 dom.window.close();
});
