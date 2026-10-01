import type { ReactNode } from "react";
import { Topbar } from "./layout";
import { Card, CardBody, Skeleton } from "./ui";
import type { Resource } from "../lib/useResource";

/** Standard page frame: Topbar + a centred main column that handles the
 *  loading / error / ready states. `children` receives the loaded data. */
export function PageChrome<T>({
  title,
  subtitle,
  resource,
  skeleton,
  children,
}: {
  title: string;
  subtitle?: string;
  resource: Resource<T>;
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  const { data, loading, error, updatedAt, refresh } = resource;
  return (
    <>
      <Topbar
        title={title}
        subtitle={subtitle}
        live={!!data}
        updatedAt={updatedAt}
        loading={loading}
        onRefresh={refresh}
      />
      <main className="mx-auto w-full max-w-[1240px] flex-1 px-4 py-5 sm:px-8 sm:py-7">
        {error ? (
          <Card>
            <CardBody>
              <h2 className="text-[15px] font-semibold text-down">Couldn't load this view</h2>
              <p className="mt-1 text-[13px] text-muted">
                The data service didn't respond. It's usually temporary — try refreshing in a
                moment.
              </p>
              {/* Dev-only hint: internal tooling must never surface publicly (H3). */}
              {import.meta.env.DEV && (
                <p className="mt-3 text-[12.5px] text-faint">
                  {error} — is the API running? Start it from the project root with{" "}
                  <code className="rounded bg-canvas px-1.5 py-0.5 text-[12px]">./start_web_ui.sh</code>
                </p>
              )}
            </CardBody>
          </Card>
        ) : !data ? (
          (skeleton ?? <DefaultSkeleton />)
        ) : (
          children(data)
        )}
      </main>
    </>
  );
}

/** A placeholder page for tabs that aren't wired yet — keeps the app navigable. */
export function StubPage({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <>
      <Topbar title={title} subtitle={subtitle} live={false} updatedAt={null} loading={false} onRefresh={() => {}} />
      <main className="mx-auto w-full max-w-[1240px] flex-1 px-4 py-5 sm:px-8 sm:py-7">
        <Card>
          <CardBody>
            <p className="text-[13.5px] text-muted">This tab is being migrated next.</p>
          </CardBody>
        </Card>
      </main>
    </>
  );
}

export function DefaultSkeleton() {
  return (
    <div className="space-y-7">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardBody>
            <Skeleton className="h-4 w-48" />
            <Skeleton className="mt-4 h-56 w-full" />
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
