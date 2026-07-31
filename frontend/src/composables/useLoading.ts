/**
 * 通用 loading / 操作锁 composable。
 *
 * 用法：
 *   const { loading, run } = useLoading()
 *   await run(async () => { ... })  // 自动管理 loading 状态，防重复调用
 *
 *   const { isLocked, lock, unlock } = useOperationLock()
 *   if (isLocked(id)) return
 *   lock(id)
 *   try { ... } finally { unlock(id) }
 */

import { ref, type Ref } from 'vue'

/**
 * 单一 loading 状态 + 防重复执行。
 */
export function useLoading() {
  const loading = ref(false)

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    if (loading.value) return undefined
    loading.value = true
    try {
      return await fn()
    } finally {
      loading.value = false
    }
  }

  return { loading, run }
}

/**
 * 按 ID 的操作锁（适用于列表中的删除/操作按钮）。
 */
export function useOperationLock() {
  const lockedIds: Ref<Set<number | string>> = ref(new Set())

  function isLocked(id: number | string): boolean {
    return lockedIds.value.has(id)
  }

  function lock(id: number | string): void {
    lockedIds.value.add(id)
  }

  function unlock(id: number | string): void {
    lockedIds.value.delete(id)
  }

  async function withLock<T>(id: number | string, fn: () => Promise<T>): Promise<T | undefined> {
    if (isLocked(id)) return undefined
    lock(id)
    try {
      return await fn()
    } finally {
      unlock(id)
    }
  }

  return { lockedIds, isLocked, lock, unlock, withLock }
}
