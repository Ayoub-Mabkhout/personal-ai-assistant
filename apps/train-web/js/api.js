// Same-origin calls to /train/api. The session is an HttpOnly cookie, so no token ever sits in page storage.
const BASE=new URL('api/',location.href.replace(/[?#].*$/,'').replace(/[^/]*$/,'')).pathname;
export class ApiError extends Error{constructor(status,message){super(message);this.status=status}}
export async function api(path,{method,body,raw,type}={}){
  const options={method:method||(body!==undefined?'POST':'GET'),credentials:'same-origin',headers:{}};
  if(body!==undefined){if(raw){options.body=body;if(type)options.headers['Content-Type']=type}else{options.body=JSON.stringify(body);options.headers['Content-Type']='application/json'}}
  let response;
  try{response=await fetch(BASE+path,options)}catch{throw new Error('offline')}
  if(!response.ok){let message='';try{message=(await response.json()).detail||''}catch{}throw new ApiError(response.status,typeof message==='string'?message:'')}
  if(response.status===204)return null;
  const kind=response.headers.get('content-type')||'';
  return kind.includes('json')?response.json():response.blob();
}
/** A same-origin URL for an authenticated image; the cookie travels with it. */
export const photoUrl=blob=>BASE+'photos/'+blob;
