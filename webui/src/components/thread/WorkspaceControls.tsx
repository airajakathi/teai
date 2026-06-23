import { type ReactNode } from "react";
import { AlertTriangle, Check, ChevronDown, Hand } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { WorkspaceAccessMode, WorkspaceScopePayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { scopeWithAccessMode } from "@/lib/workspace";

export { WorkspaceProjectPicker } from "./WorkspaceProjectPicker";

export function WorkspaceAccessMenu({
  scope,
  disabled,
  canUseFullAccess,
  isHero,
  onChange,
}: {
  scope: WorkspaceScopePayload;
  disabled?: boolean;
  canUseFullAccess: boolean;
  isHero: boolean;
  onChange?: (scope: WorkspaceScopePayload) => void;
}) {
  const { t } = useTranslation();
  const mode = scope.access_mode;
  const isFull = mode === "full";

  const setMode = (value: WorkspaceAccessMode) => {
    if (value === "full" && !canUseFullAccess) return;
    if (value === mode) return;
    onChange?.(scopeWithAccessMode(scope, value));
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled || !onChange}>
        <Button
          type="button"
          variant="ghost"
          aria-label={t("thread.composer.workspace.accessAria")}
          className={cn(
            "max-w-[12.5rem] rounded-[10px] border border-transparent font-semibold shadow-none",
            isHero ? "h-8 px-2.5 text-[12px]" : "h-9 px-3 text-[12.5px]",
            isFull
              ? "bg-transparent text-orange-600 hover:bg-orange-500/8 dark:text-orange-300 dark:hover:bg-orange-400/10"
              : "bg-transparent text-muted-foreground hover:bg-foreground/[0.045] hover:text-foreground dark:hover:bg-white/[0.06]",
          )}
        >
          {isFull ? (
            <AlertTriangle className={cn("mr-1.5 shrink-0", isHero ? "h-3.5 w-3.5" : "h-3.5 w-3.5")} />
          ) : (
            <Hand className={cn("mr-1.5 shrink-0", isHero ? "h-3.5 w-3.5" : "h-3.5 w-3.5")} />
          )}
          <span className="truncate">
            {t(isFull ? "thread.composer.workspace.full" : "thread.composer.workspace.default")}
          </span>
          <ChevronDown className={cn("ml-1.5 shrink-0", isHero ? "h-3 w-3" : "h-3 w-3")} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <AccessMenuItem
          icon={<Hand className="h-4 w-4" />}
          label={t("thread.composer.workspace.default")}
          selected={mode === "restricted"}
          onSelect={() => setMode("restricted")}
        />
        <AccessMenuItem
          icon={<AlertTriangle className="h-4 w-4" />}
          label={t("thread.composer.workspace.full")}
          selected={mode === "full"}
          disabled={!canUseFullAccess}
          warning
          onSelect={() => setMode("full")}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function AccessMenuItem({
  icon,
  label,
  selected,
  disabled,
  warning,
  onSelect,
}: {
  icon: ReactNode;
  label: string;
  selected: boolean;
  disabled?: boolean;
  warning?: boolean;
  onSelect: () => void;
}) {
  return (
    <DropdownMenuItem
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex h-10 items-center gap-3 rounded-xl px-3 text-[13.5px] font-semibold",
        warning && "text-orange-600 focus:text-orange-600 dark:text-orange-300 dark:focus:text-orange-300",
      )}
    >
      <span className="grid h-5 w-5 shrink-0 place-items-center text-current" aria-hidden>
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {selected ? <Check className="h-4 w-4 shrink-0" aria-hidden /> : null}
    </DropdownMenuItem>
  );
}
