import { useSearchParams } from 'react-router-dom';
import type { SetStateAction } from 'react';

// Keep list state in the URL so both browser Back and explicit return links restore it.
export function useListParameter<T extends string | number | boolean>(key: string, initial: T) {
  const [params, setParams] = useSearchParams();
  const raw = params.get(key);
  let value = initial;
  if (raw !== null) {
    if (typeof initial === 'number') {
      const number = Number(raw);
      if (Number.isSafeInteger(number) && number >= (key === 'page' ? 1 : 0)) value = number as T;
    } else if (typeof initial === 'boolean') value = (raw === 'true') as T;
    else value = raw as T;
  }
  const set = (next: SetStateAction<T>) => {
    const updated = typeof next === 'function' ? next(value) : next;
    setParams(
      (previous) => {
        const copy = new URLSearchParams(previous);
        if (updated === initial) copy.delete(key);
        else copy.set(key, String(updated));
        if (key !== 'page') copy.delete('page');
        return copy;
      },
      { replace: true },
    );
  };
  return [value, set] as const;
}
