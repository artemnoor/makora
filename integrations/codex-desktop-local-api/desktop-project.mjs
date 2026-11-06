import { win32 } from 'node:path';

export function desktopProjectForDirectory(projects, directory) {
  const normalize = value => win32.normalize(String(value).replace(/^\\\\\?\\/, '')).replace(/[\\/]+$/, '').toLowerCase();
  const wanted = normalize(directory);
  let best = null;
  let length = -1;
  for (const project of projects) {
    for (const root of project.roots || []) {
      const path = normalize(typeof root === 'string' ? root : root.path || '');
      if (path && path.length > length && (wanted === path || wanted.startsWith(path + '\\'))) {
        best = project.id;
        length = path.length;
      }
    }
  }
  return best;
}
