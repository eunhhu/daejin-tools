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
 doc.querySelector('#booking-end').value='17:30';
 doc.querySelector('#booking-purpose').value='개인 학습';
 doc.querySelector('#booking-ack').checked=true;
 doc.querySelector('#booking-ack').dispatchEvent(new dom.window.Event('change'));
 assert.equal(doc.querySelector('#booking-confirm').disabled,false);
 doc.querySelector('#booking-confirm').click();doc.querySelector('#booking-confirm').click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,2);assert.equal(calls[1].body.confirmed,true);
 assert.equal(calls[1].body.purpose,'개인 학습');assert.equal(invalidated,1);
 assert.match(doc.querySelector('#booking-result').textContent,/123/);
 for(const id of ['booking-end','booking-purpose','booking-ack']) assert.equal(doc.querySelector('#'+id).disabled,true);
 assert.equal(doc.querySelector('#booking-confirm').disabled,true);
 dom.window.close();
});
