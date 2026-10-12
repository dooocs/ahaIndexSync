export interface Gateways {
  publicUrl: string;
  serviceUrl: string;
}

function gatewayOrigin(value: string, internal: boolean) {
  let url: URL;
  try { url = new URL(value); }
  catch { throw new Error('Invalid community gateway configuration'); }
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((!['http:', 'https:'].includes(url.protocol)) ||
      (!internal && url.protocol !== 'https:' && !local) ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Invalid community gateway configuration');
  }
  return url.origin;
}

export function communityGateways(publicUrl: string, localUrl?: string): Gateways {
  const publicOrigin = gatewayOrigin(publicUrl, false);
  return { publicUrl: publicOrigin, serviceUrl: localUrl ? gatewayOrigin(localUrl, true) : publicOrigin };
}

export function publicPhotoUrl(value: string, gateways: Gateways) {
  let signed: URL;
  try { signed = new URL(value); }
  catch { throw new Error('Invalid signed photo URL'); }
  if (![gateways.publicUrl, gateways.serviceUrl].includes(signed.origin) ||
      signed.username || signed.password || signed.hash ||
      !signed.pathname.startsWith('/storage/v1/object/sign/meet-photos/') ||
      !signed.searchParams.get('token')) {
    throw new Error('Invalid signed photo URL');
  }
  const publicUrl = new URL(gateways.publicUrl);
  publicUrl.pathname = signed.pathname;
  publicUrl.search = signed.search;
  return publicUrl.href;
}
