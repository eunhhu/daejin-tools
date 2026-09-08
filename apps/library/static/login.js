export function bootLogin(doc = document, fetcher = globalThis.fetch,
  navigate = url => doc.defaultView?.location.replace(url)) {
  const cookie = name => {
    const value=doc.cookie.split('; ').find(item=>item.startsWith(`${name}=`));
    return value?decodeURIComponent(value.slice(name.length+1)):'';
  };
  const form=doc.querySelector('#login-form'),status=doc.querySelector('#login-status');
  const submit=doc.querySelector('#login-submit'),account=doc.querySelector('#school-account');
  const password=doc.querySelector('#school-password');

  form?.addEventListener('submit',async event=>{
    event.preventDefault();submit.disabled=true;status.textContent='로그인 중이야.';
    try {
      const response=await fetcher('/api/login',{method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{'Content-Type':'application/json','X-Library-CSRF':cookie('daejin_library_login_csrf')},
        body:JSON.stringify({account_id:account.value,password:password.value})});
      if(!response.ok) {
        let message='로그인할 수 없어.';
        try {
          const data=await response.json();
          if(typeof data.detail==='string') message=data.detail;
        } catch {}
        throw new Error(message);
      }
      password.value='';navigate('/');
    } catch(error) {status.textContent=error.message||'로그인할 수 없어.';submit.disabled=false;}
  });
}

if(typeof document!=='undefined') bootLogin();
