import {detailURL} from './model.js';

export function createBookingUI(doc, fetcher, config, invalidate, reauthenticate = () => {}) {
  const $ = sel => doc.querySelector(sel), dialog = $('#slot-dialog');
  let quote = null, busy = false, locked = false, serial = 0, expires = 0, selectedEnd = '';
  const duration = (start, end) => {
    const [startHour,startMinute]=start.split(':').map(Number),[endHour,endMinute]=end.split(':').map(Number);
    const minutes=endHour*60+endMinute-startHour*60-startMinute;
    const hours=Math.floor(minutes/60), remainder=minutes%60;
    return `${hours ? `${hours}시간${remainder ? ' ' : ''}` : ''}${remainder ? `${remainder}분` : ''}`;
  };
  const selectEnd = (value, focus = false) => {
    if (busy || locked || !quote || !quote.ends.includes(value)) return;
    selectedEnd=value;
    for (const button of doc.querySelectorAll('#booking-end-options button')) {
      button.setAttribute('aria-pressed',String(button.dataset.end===selectedEnd));
      if (focus && button.dataset.end===selectedEnd) button.focus();
    }
    sync();
  };
  const sync = () => {
    const purpose = $('#booking-purpose').value.trim();
    $('#booking-confirm').disabled = busy || locked || !quote || !quote.ends.includes(selectedEnd) ||
      purpose.length > 300 || !$('#booking-ack').checked;
    $('#booking-close').disabled = busy;
    for (const id of ['booking-purpose','booking-ack']) $('#'+id).disabled = busy || locked;
    for (const button of doc.querySelectorAll('#booking-end-options button')) button.disabled = busy || locked;
    $('#booking-summary').textContent = quote && selectedEnd ?
      `${quote.date} · ${quote.start}–${selectedEnd} · ${duration(quote.start,selectedEnd)} · 한국 시간` :
      '종료 시간을 선택하세요.';
  };
  const post = async (path, body) => {
    const response = await fetcher(path, {method:'POST',credentials:'same-origin',cache:'no-store',
      signal:AbortSignal.timeout(90000), headers:{'Content-Type':'application/json','X-Library-CSRF':config().csrf_token || ''},
      body:JSON.stringify(body)});
    if (response.status === 401) {
      reauthenticate();
      throw new Error('도서관 로그인이 만료되었습니다. 다시 로그인이 필요합니다.');
    }
    if (!response.ok) {
      let message = '예약 요청을 처리할 수 없습니다.';
      try {
        const data = await response.json();
        if (typeof data.detail === 'string') message = data.detail;
      } catch {}
      throw new Error(message);
    }
    try {
      return await response.json();
    } catch {
      throw new Error('예약 요청을 처리할 수 없습니다.');
    }
  };
  for (const id of ['booking-purpose','booking-ack']) {
    $('#'+id).addEventListener('input',sync);$('#'+id).addEventListener('change',sync);
  }
  $('#booking-close').addEventListener('click',()=>{if (!busy) {serial++;quote=null;dialog.close();}});
  dialog.addEventListener('cancel',event=>{if (busy) event.preventDefault(); else {serial++;quote=null;}});
  $('#booking-confirm').addEventListener('click',async()=>{
    sync();if ($('#booking-confirm').disabled) return;
    if (Date.now() >= expires) {locked=true;$('#booking-result').textContent='예약 준비가 만료되었습니다. 창을 닫고 시간 칸을 다시 선택하세요.';sync();return;}
    const payload = {ticket:quote.ticket,end:selectedEnd,purpose:$('#booking-purpose').value.trim(),confirmed:true};
    busy=true;sync();$('#booking-result').textContent='예약 요청 처리 및 공식 내역 확인 중입니다. 중복 제출하지 마세요.';
    try {
      const result = await post('/api/booking/confirm',payload);
      locked=true;
      if (result.status === 'confirmed' && /^\d+$/.test(result.reservation_id)) {
        $('#booking-result').textContent=`예약 확인 완료 · 내역 번호 ${result.reservation_id}\n${result.message}`;
        invalidate(result);
      } else if (result.status === 'rejected') {
        $('#booking-result').textContent=`예약되지 않았습니다. ${result.message}`;
      } else {
        $('#booking-result').textContent=`결과 미확인. ${result.message || '공식 내역 확인 전에는 다시 예약하지 마세요.'}`;
        invalidate(result);
      }
    } catch (error) {
      locked=true;$('#booking-result').textContent=`예약 완료를 확인할 수 없습니다. ${error.message}\n공식 예약 내역 확인 전에는 다시 제출하지 마세요.`;
      invalidate({status:'unknown'});
    } finally {busy=false;sync();}
  });
  return {async open(room, day, start) {
    if (busy) return;
    const ticket = ++serial;
    quote=null;locked=false;selectedEnd='';$('#booking-fields').hidden=true;$('#booking-result').textContent='선택한 시작 시간의 종료 시간을 확인하는 중입니다.';
    $('#slot-room').textContent=room.name;$('#slot-time').textContent=`${day} · ${start} 시작`;
    $('#reserve-link').href=detailURL(room,day);$('#booking-account').textContent='';
    $('#booking-purpose').value='';$('#booking-ack').checked=false;sync();
    if (!dialog.open) dialog.showModal();
    if (!config().booking_enabled) {$('#booking-result').textContent='예약 기능이 연결되지 않았습니다. 공식 상세 화면 이용이 필요합니다.';return;}
    try {
      const data = await post('/api/booking/prepare',{date:day,room_code:room.code,start});
      if (serial !== ticket) return;
      if (data.date !== day || data.start !== start || !Array.isArray(data.ends) || !data.ticket) throw new Error('예약 준비 응답을 확인할 수 없습니다.');
      quote=data;expires=Date.now()+data.expires_in_seconds*1000;
      const options=$('#booking-end-options');options.replaceChildren();
      for (const [index,value] of data.ends.entries()) {
        const button=doc.createElement('button');button.type='button';button.className='end-time-option';button.dataset.end=value;
        button.setAttribute('aria-pressed','false');button.setAttribute('aria-label',`${value} 종료, ${duration(start,value)}`);
        const time=doc.createElement('strong');time.textContent=value;
        const length=doc.createElement('span');length.textContent=duration(start,value);
        button.append(time,length);
        button.addEventListener('click',()=>selectEnd(value));
        button.addEventListener('keydown',event=>{
          if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
          event.preventDefault();
          const last=data.ends.length-1;
          const next=event.key==='Home'?0:event.key==='End'?last:
            ['ArrowRight','ArrowDown'].includes(event.key)?(index+1)%data.ends.length:(index+last)%data.ends.length;
          selectEnd(data.ends[next],true);
        });
        options.append(button);
      }
      $('#booking-account').textContent=data.account_notice;$('#booking-fields').hidden=false;
      $('#booking-result').textContent='예약 전 상태입니다. 내용을 확인한 후 예약 확정을 선택하세요.';sync();
    } catch (error) {if (serial === ticket) $('#booking-result').textContent=error.message;}
  }};
}
