import { useEffect, useState } from "react";

import { fetchSkills } from "@/lib/api";
import type { SkillSummary } from "@/lib/types";

export interface UseSkillsResult {
  skills: SkillSummary[];
  loading: boolean;
  loadFailed: boolean;
}

export function useSkills(token: string): UseSkillsResult {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    fetchSkills(token)
      .then(({ skills: nextSkills }) => {
        if (!cancelled) {
          setSkills(nextSkills);
          setLoadFailed(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSkills([]);
          setLoadFailed(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return { skills, loading, loadFailed };
}
