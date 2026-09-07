import {detailURL} from './model.js';

export function createBookingUI(doc, fetcher, config, invalidate) {
  const $ = sel => doc.querySelector(sel), dialog = $('#slot-dialog');
  let quote = null, busy = false, locked = false, serial = 0, expires = 0;
  const sync = () => {
    const end = $('#booking-end').value, purpose = $('#booking-purpose').value.trim();
    $('#booking-confirm').disabled = busy || locked || !quote || !quote.ends.includes(end) ||
      !purpose || purpose.length > 300 || !$('#booking-ack').checked;
    $('#booking-close').disabled = busy;
    for (const id of ['booking-end','booking-purpose','booking-ack']) $('#'+id).disabled = busy || locked;
    $('#booking-summary').textContent = quote && end ? `${quote.date} · ${quote.start}–${end} · 한국 시간` : '종료 시간을 선택해 줘.';
  };
  const post = async (path, body) => {
    const response = await fetcher(path, {method:'POST',credentials:'same-origin',cache:'no-store',
      signal:AbortSignal.timeout(90000), headers:{'Content-Type':'application/json','X-Library-CSRF':config().csrf_token || ''},
      body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '예약 요청을 처리하지 못했어.');
    return data;
  };
  for (const id of ['booking-end','booking-purpose','booking-ack']) {
    $('#'+id).addEventListener('input',sync);$('#'+id).addEventListener('change',sync);
  }
  $('#booking-close').addEventListener('click',()=>{if (!busy) {serial++;quote=null;dialog.close();}});
  dialog.addEventListener('cancel',event=>{if (busy) event.preventDefault(); else {serial++;quote=null;}});
  $('#booking-confirm').addEventListener('click',async()=>{
    sync();if ($('#booking-confirm').disabled) return;
    if (Date.now() >= expires) {locked=true;$('#booking-result').textContent='예약 준비가 만료됐어. 닫고 시간 칸을 다시 선택해 줘.';sync();return;}
    const payload = {ticket:quote.ticket,end:$('#booking-end').value,purpose:$('#booking-purpose').value.trim(),confirmed:true};
    busy=true;sync();$('#booking-result').textContent='예약 요청 중이야. 중복 제출하지 않고 내역까지 확인할게.';
    try {
      const result = await post('/api/booking/confirm',payload);
      locked=true;
      if (result.status === 'confirmed' && /^\d+$/.test(result.reservation_id)) {
        $('#booking-result').textContent=`예약 확인 완료 · 내역 번호 ${result.reservation_id}\n${result.message}`;
        invalidate(result);
      } else if (result.status === 'rejected') {
        $('#booking-result').textContent=`예약되지 않았어. ${result.message}`;
      } else {
        $('#booking-result').textContent=`결과 미확인. ${result.message || '공식 내역 확인 전 다시 예약하지 마.'}`;
        invalidate(result);
      }
    } catch (error) {
      locked=true;$('#booking-result').textContent=`예약 완료로 확인되지 않았어. ${error.message}\n공식 예약 내역 확인 전 다시 제출하지 마.`;
      invalidate({status:'unknown'});
    } finally {busy=false;sync();}
  });
  return {async open(room, day, start) {
    if (busy) return;
    const ticket = ++serial;
    quote=null;locked=false;$('#booking-fields').hidden=true;$('#booking-result').textContent='선택한 시작 시간의 종료 시간을 확인 중이야. 아직 예약하지 않아.';
    $('#slot-room').textContent=room.name;$('#slot-time').textContent=`${day} · ${start} 시작`;
    $('#reserve-link').href=detailURL(room,day);$('#booking-account').textContent='';
    $('#booking-purpose').value='';$('#booking-ack').checked=false;sync();
    if (!dialog.open) dialog.showModal();
    if (!config().booking_enabled) {$('#booking-result').textContent='예약 기능이 연결되지 않았어. 공식 상세 화면을 이용해 줘.';return;}
    try {
      const data = await post('/api/booking/prepare',{date:day,room_code:room.code,start});
      if (serial !== ticket) return;
      if (data.date !== day || data.start !== start || !Array.isArray(data.ends) || !data.ticket) throw new Error('예약 준비 응답을 확인할 수 없어.');
      quote=data;expires=Date.now()+data.expires_in_seconds*1000;
      $('#booking-end').replaceChildren();
      for (const value of ['',...data.ends]) {
        const option=doc.createElement('option');option.value=value;option.textContent=value || '종료 시간 선택';
        $('#booking-end').append(option);
      }
      $('#booking-account').textContent=data.account_notice;$('#booking-fields').hidden=false;
      $('#booking-result').textContent='아직 예약 전이야. 내용을 확인한 뒤 예약 확정을 눌러 줘.';sync();
    } catch (error) {if (serial === ticket) $('#booking-result').textContent=error.message;}
  }};
}
