/**
 * What the current user may do, to hide buttons they can't use.
 * The backend enforces the same rules; hiding is only for a clear interface.
 */
import type { Role } from "../api/types.ts";
import { useAuth } from "../auth/context.ts";

const CLASSIFY: Role[] = ["machine_operator", "production_supervisor", "factory_manager", "platform_admin"];
const BULK_CLASSIFY: Role[] = ["production_supervisor", "factory_manager", "platform_admin"];
const MANAGE_REASONS: Role[] = ["factory_manager", "platform_admin"];
const SUPERVISORS_AND_ABOVE: Role[] = ["production_supervisor", "factory_manager", "platform_admin"];
const REQUEST_MAINTENANCE: Role[] = [
  "machine_operator",
  "quality_inspector",
  "maintenance_technician",
  "production_supervisor",
  "factory_manager",
  "platform_admin",
];
const REVIEW_QUALITY: Role[] = ["quality_inspector", "production_supervisor", "factory_manager", "platform_admin"];

export interface Permissions {
  canClassify: boolean;
  canBulkClassify: boolean;
  canManageReasons: boolean;
  canReviewQuality: boolean;
  /** Defect types and inspection stations (the same managers as reasons). */
  canManageQuality: boolean;
  /** Resolve alerts by hand and see the alert engine's health. */
  canResolveAlerts: boolean;
  canManageAlertRules: boolean;
  canRequestMaintenance: boolean;
  /** Assign, set priority and due date, cancel, verify. */
  canPlanMaintenance: boolean;
  isTechnician: boolean;
}

export function permissionsFor(role: Role | null | undefined): Permissions {
  return {
    canClassify: role ? CLASSIFY.includes(role) : false,
    canBulkClassify: role ? BULK_CLASSIFY.includes(role) : false,
    canManageReasons: role ? MANAGE_REASONS.includes(role) : false,
    canReviewQuality: role ? REVIEW_QUALITY.includes(role) : false,
    canManageQuality: role ? MANAGE_REASONS.includes(role) : false,
    canResolveAlerts: role ? SUPERVISORS_AND_ABOVE.includes(role) : false,
    canManageAlertRules: role ? MANAGE_REASONS.includes(role) : false,
    canRequestMaintenance: role ? REQUEST_MAINTENANCE.includes(role) : false,
    canPlanMaintenance: role ? SUPERVISORS_AND_ABOVE.includes(role) : false,
    isTechnician: role === "maintenance_technician",
  };
}

export function usePermissions(): Permissions {
  return permissionsFor(useAuth().user?.role);
}
