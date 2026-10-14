/**
 * What the current user may do, to hide buttons they can't use.
 * The backend enforces the same rules; hiding is only for a clear interface.
 */
import type { Role } from "../api/types.ts";
import { useAuth } from "../auth/context.ts";

const CLASSIFY: Role[] = ["machine_operator", "production_supervisor", "factory_manager", "platform_admin"];
const BULK_CLASSIFY: Role[] = ["production_supervisor", "factory_manager", "platform_admin"];
const MANAGE_REASONS: Role[] = ["factory_manager", "platform_admin"];

export interface Permissions {
  canClassify: boolean;
  canBulkClassify: boolean;
  canManageReasons: boolean;
}

export function permissionsFor(role: Role | null | undefined): Permissions {
  return {
    canClassify: role ? CLASSIFY.includes(role) : false,
    canBulkClassify: role ? BULK_CLASSIFY.includes(role) : false,
    canManageReasons: role ? MANAGE_REASONS.includes(role) : false,
  };
}

export function usePermissions(): Permissions {
  return permissionsFor(useAuth().user?.role);
}
