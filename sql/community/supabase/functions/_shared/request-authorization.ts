export function requestAuthorization(headers: Headers) {
  // The Aliyun function gateway may replace the standard Authorization header.
  return headers.get('x-community-authorization') ?? headers.get('authorization');
}
