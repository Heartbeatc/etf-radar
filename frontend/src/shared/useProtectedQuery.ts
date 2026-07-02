import { useQuery } from '@tanstack/react-query';

export function useProtectedQuery<T>(queryKey: readonly unknown[], token: string, queryFn: (context: { signal?: AbortSignal }) => Promise<T>, refetchInterval: number | false) {
  return useQuery({ queryKey, queryFn, enabled: Boolean(token), refetchInterval, retry: false });
}
