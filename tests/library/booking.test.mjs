import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {createBookingUI} from '../../apps/library/static/booking-ui.js';
const html=await readFile(new URL('../../apps/library/static/index.html',import.meta.url),'utf8');

test('opening prepares only; explicit acknowledged confirmation submits once',async()=>{
 const dom=new JSDOM(html,{url:'http://localhost/'}),doc=dom.window.document,calls=[];
 const dialog=doc.querySelector('#slot-dialog');dialog.showModal=()=>{dialog.open=true;};dialog.close=()=>{dialog.open=false;};
 const fetcher=async(url,init)=>{calls.push({url,body:JSON.parse(init.body)});return {ok:true,json:async()=>url.endsWith('/prepare')?
  {ticket:'synthetic-ticket-123456789',date:'2026-09-07',start:'17:00',ends:['17:30'],expires_in_seconds:120,account_notice:'테스트 계정'}:
  {status:'confirmed',reservation_id:'123',message:'합성 예약 내역 확인'}};};
 let invalidated=0;
 const ui=createBookingUI(doc,fetcher,()=>({csrf_token:'synthetic',booking_enabled:true}),()=>invalidated++);
 await ui.open({code:'S01',name:'테스트실'},'2026-09-07','17:00');
 assert.equal(calls.length,1);assert.equal(doc.querySelector('#booking-confirm').disabled,true);
 const end=doc.querySelector('#booking-end-options button');end.click();
 doc.querySelector('#booking-purpose').value='개인 학습';
 doc.querySelector('#booking-ack').checked=true;
 doc.querySelector('#booking-ack').dispatchEvent(new dom.window.Event('change'));
 assert.equal(doc.querySelector('#booking-confirm').disabled,false);
 doc.querySelector('#booking-confirm').click();doc.querySelector('#booking-confirm').click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,2);assert.equal(calls[1].body.confirmed,true);
 assert.equal(calls[1].body.purpose,'개인 학습');assert.equal(invalidated,1);
 assert.match(doc.querySelector('#booking-result').textContent,/123/);
 for(const id of ['booking-purpose','booking-ack']) assert.equal(doc.querySelector('#'+id).disabled,true);
 assert.equal(end.disabled,true);
 assert.equal(doc.querySelector('#booking-confirm').disabled,true);
 dom.window.close();
});

test('end-time timeline exposes duration and sends the pressed choice with optional purpose',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/'}),doc=dom.window.document,calls=[];
 const dialog=doc.querySelector('#slot-dialog');dialog.showModal=()=>{dialog.open=true;};dialog.close=()=>{dialog.open=false;};
 const fetcher=async(url,init)=>{calls.push({url,body:JSON.parse(init.body)});return {ok:true,json:async()=>url.endsWith('/prepare')?
  {ticket:'synthetic-ticket-123456789',date:'2026-09-08',start:'17:00',ends:['17:30','18:30'],expires_in_seconds:120,account_notice:'20****34 계정'}:
  {status:'confirmed',reservation_id:'456',message:'합성 예약 내역 확인'}};};
 const ui=createBookingUI(doc,fetcher,()=>({csrf_token:'synthetic',booking_enabled:true}),()=>{});
 await ui.open({code:'S01',name:'테스트실'},'2026-09-08','17:00');

 const choices=[...doc.querySelectorAll('#booking-end-options button')];
 assert.equal(choices.length,2);
 assert.match(choices[0].textContent,/17:30/);
 assert.match(choices[0].textContent,/30분/);
 assert.match(choices[1].textContent,/18:30/);
 assert.match(choices[1].textContent,/1시간 30분/);
 assert.equal(choices[0].getAttribute('aria-pressed'),'false');
 choices[0].focus();
 choices[0].dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
 assert.equal(choices[0].getAttribute('aria-pressed'),'false');
 assert.equal(choices[1].getAttribute('aria-pressed'),'true');
 assert.equal(doc.activeElement,choices[1]);
 assert.match(doc.querySelector('#booking-summary').textContent,/1시간 30분/);

 doc.querySelector('#booking-ack').checked=true;
 doc.querySelector('#booking-ack').dispatchEvent(new dom.window.Event('change'));
 assert.equal(doc.querySelector('#booking-confirm').disabled,false);
 doc.querySelector('#booking-confirm').click();
 doc.querySelector('#booking-confirm').click();
 await new Promise(resolve=>setImmediate(resolve));

 assert.equal(calls.length,2);
 assert.equal(calls[1].body.end,'18:30');
 assert.equal(calls[1].body.purpose,'');
 assert.equal(calls[1].body.confirmed,true);
 assert.equal(choices[1].disabled,true);
 dom.window.close();
});

test('booking redirects on an empty 401 before attempting JSON parsing',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/'}),doc=dom.window.document,navigations=[];
 const dialog=doc.querySelector('#slot-dialog');dialog.showModal=()=>{dialog.open=true;};dialog.close=()=>{dialog.open=false;};
 const fetcher=async()=>({status:401,ok:false,json:async()=>{throw new Error('synthetic JSON parse');}});
 const ui=createBookingUI(doc,fetcher,()=>({csrf_token:'synthetic',booking_enabled:true}),()=>{},()=>navigations.push('/login'));

 await ui.open({code:'S01',name:'테스트실'},'2026-09-08','17:00');

 assert.deepEqual(navigations,['/login']);
 dom.window.close();
});

test('booking shows generic text for a non-JSON error response',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/'}),doc=dom.window.document;
 const dialog=doc.querySelector('#slot-dialog');dialog.showModal=()=>{dialog.open=true;};dialog.close=()=>{dialog.open=false;};
 const fetcher=async()=>({status:503,ok:false,json:async()=>{throw new Error('synthetic JSON parse');}});
 const ui=createBookingUI(doc,fetcher,()=>({csrf_token:'synthetic',booking_enabled:true}),()=>{});

 await ui.open({code:'S01',name:'테스트실'},'2026-09-08','17:00');

 assert.equal(doc.querySelector('#booking-result').textContent,'예약 요청을 처리하지 못했어.');
 dom.window.close();
});
