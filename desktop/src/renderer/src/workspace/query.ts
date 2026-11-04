import { QueryClient } from '@tanstack/react-query'

/** One query cache for the workspace window, also used by the action cards inside AG Studio widgets. */
export const client = new QueryClient({ defaultOptions: { queries: { retry: 2, refetchOnWindowFocus: false } } })
