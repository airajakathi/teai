import { createContext, useContext, type ReactNode } from "react";

import type { TeaiBuilderClient } from "@/lib/teai_builder-client";

interface ClientContextValue {
  client: TeaiBuilderClient;
  token: string;
  modelName: string | null;
}

const ClientContext = createContext<ClientContextValue | null>(null);

export function ClientProvider({
  client,
  token,
  modelName = null,
  children,
}: {
  client: TeaiBuilderClient;
  token: string;
  modelName?: string | null;
  children: ReactNode;
}) {
  return (
    <ClientContext.Provider value={{ client, token, modelName }}>
      {children}
    </ClientContext.Provider>
  );
}

export function useClient(): ClientContextValue {
  const ctx = useContext(ClientContext);
  if (!ctx) {
    throw new Error("useClient must be used within a ClientProvider");
  }
  return ctx;
}
