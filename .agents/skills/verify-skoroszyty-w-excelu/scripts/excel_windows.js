// Excel's on-screen windows as "layer | title | width x height", one per line; titles need Screen Recording.
ObjC.import('CoreGraphics');
ObjC.import('Foundation');
function run() {
  const list = ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, 0));
  const out = [];
  for (let i = 0; i < list.count; i++) {
    const w = list.objectAtIndex(i);
    if (ObjC.unwrap(w.objectForKey('kCGWindowOwnerName')) !== 'Microsoft Excel') continue;
    const b = w.objectForKey('kCGWindowBounds');
    out.push([ObjC.unwrap(w.objectForKey('kCGWindowLayer')), ObjC.unwrap(w.objectForKey('kCGWindowName')) || '',
      ObjC.unwrap(b.objectForKey('Width')) + 'x' + ObjC.unwrap(b.objectForKey('Height'))].join(' | '));
  }
  return out.join('\n');
}
