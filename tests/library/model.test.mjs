import test from 'node:test';
import assert from 'node:assert/strict';
import {filterRooms, cellState, timeAxis, kstNow, detailURL} from '../../apps/library/static/model.js';

const rooms = [
  {code:'C01',group:'C',name:'캐럴1실',capacity:1,minimum:1,starts:['17:00'],step_minutes:30,state:'ok'},
  {code:'S01',group:'S',name:'제1세미나실',capacity:8,minimum:1,starts:['09:00','09:30'],step_minutes:30,state:'ok'},
];
test('room type and participant filters are purely local', () => {
  assert.deepEqual(filterRooms(rooms,'S',3),[rooms[1]]);
  assert.deepEqual(filterRooms(rooms,'all',9),[]);
});
test('missing times are unavailable, failures unknown, elapsed times not free', () => {
  assert.equal(cellState(rooms[0],'17:00','2026-09-07',{date:'2026-09-07',time:'10:00'}),'available');
  assert.equal(cellState(rooms[0],'17:30','2026-09-07',{date:'2026-09-07',time:'10:00'}),'unavailable');
  assert.equal(cellState({...rooms[0],state:'unknown'},'17:00','2026-09-07',{date:'2026-09-07',time:'10:00'}),'unknown');
  assert.equal(cellState(rooms[1],'09:00','2026-09-07',{date:'2026-09-07',time:'10:00'}),'elapsed');
  assert.equal(cellState(rooms[1],'09:00','2026-09-08',{date:'2026-09-07',time:'10:00'}),'available');
});
test('Korean dates are independent of browser timezone',()=>{
  assert.deepEqual(kstNow(new Date('2026-09-06T16:00:00Z')),{date:'2026-09-07',time:'01:00'});
});
test('axis includes starts outside the reference hours without inventing availability',()=>{
  const axis=timeAxis([{...rooms[0],starts:['07:15','21:00'],step_minutes:15}]);
  assert.equal(axis[0],'07:15');
  assert.equal(axis.at(-1),'21:00');
  assert.equal(new Set(axis).size,axis.length);
});
test('official detail link contains only room navigation, never reservations or credentials',()=>{
  const url=new URL(detailURL(rooms[1],'2026-09-07'));
  assert.equal(url.origin,'https://library.daejin.ac.kr');
  assert.equal(url.pathname,'/seminar_resv.mir');
  assert.equal(url.searchParams.get('seminar_code'),'S01');
  assert.equal(url.searchParams.get('resv_datev'),'2026-09-07');
  assert.ok(!url.search.includes('password'));
});
