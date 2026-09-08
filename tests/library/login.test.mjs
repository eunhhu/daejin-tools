import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {bootLogin} from '../../apps/library/static/login.js';

const html=await readFile(new URL('../../apps/library/static/login.html',import.meta.url),'utf8');

test('native login form can only submit credentials with POST to the login endpoint',()=>{
 const dom=new JSDOM(html,{url:'https://localhost/login'}),form=dom.window.document.querySelector('#login-form');
 assert.equal(form.method,'post');
 assert.equal(form.getAttribute('action'),'/api/login');
 dom.window.close();
});

test('login sends bounded credentials only in JSON with preauth csrf',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/login'}),doc=dom.window.document,calls=[],navigations=[];
 doc.cookie='daejin_library_login_csrf=preauth-token; Secure; Path=/';
 const fetcher=async(url,init)=>{calls.push({url,init});return {ok:true,status:200,json:async()=>({ok:true,account_label:'20****34'})};};
 bootLogin(doc,fetcher,url=>navigations.push(url));
 doc.querySelector('#school-account').value='20261234';
 doc.querySelector('#school-password').value='synthetic-password';
 doc.querySelector('#login-form').dispatchEvent(new dom.window.Event('submit',{cancelable:true}));
 await new Promise(resolve=>setImmediate(resolve));

 assert.equal(calls.length,1);
 assert.equal(calls[0].url,'/api/login');
 assert.equal(calls[0].init.headers['X-Library-CSRF'],'preauth-token');
 assert.deepEqual(JSON.parse(calls[0].init.body),{account_id:'20261234',password:'synthetic-password'});
 assert.ok(!calls[0].url.includes('20261234'));
 assert.ok(!calls[0].url.includes('synthetic-password'));
 assert.ok(!html.includes('synthetic-password'));
 assert.deepEqual(navigations,['/']);
 dom.window.close();
});

test('login shows generic text for an empty or non-JSON failure',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/login'}),doc=dom.window.document,navigations=[];
 doc.cookie='daejin_library_login_csrf=preauth-token; Secure; Path=/';
 const fetcher=async()=>({ok:false,status:401,json:async()=>{throw new Error('synthetic JSON parse');}});
 bootLogin(doc,fetcher,url=>navigations.push(url));
 doc.querySelector('#school-account').value='20261234';
 doc.querySelector('#school-password').value='wrong-password';

 doc.querySelector('#login-form').dispatchEvent(new dom.window.Event('submit',{cancelable:true}));
 await new Promise(resolve=>setImmediate(resolve));

 assert.equal(doc.querySelector('#login-status').textContent,'로그인할 수 없습니다.');
 assert.deepEqual(navigations,[]);
 dom.window.close();
});

test('successful login does not require a JSON response body',async()=>{
 const dom=new JSDOM(html,{url:'https://localhost/login'}),doc=dom.window.document,navigations=[];
 doc.cookie='daejin_library_login_csrf=preauth-token; Secure; Path=/';
 const fetcher=async()=>({ok:true,status:204,json:async()=>{throw new Error('empty response');}});
 bootLogin(doc,fetcher,url=>navigations.push(url));
 doc.querySelector('#school-account').value='20261234';
 doc.querySelector('#school-password').value='synthetic-password';

 doc.querySelector('#login-form').dispatchEvent(new dom.window.Event('submit',{cancelable:true}));
 await new Promise(resolve=>setImmediate(resolve));

 assert.deepEqual(navigations,['/']);
 dom.window.close();
});
