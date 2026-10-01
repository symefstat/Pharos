import { useEffect, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { Info, Lock, Scale } from "lucide-react";
import { Card, CardBody, SectionHeading } from "../components/ui";

/* Legal — the public terms / privacy / about page, in the same prose-document
   register as Methodology. Three anchored sections (#terms, #privacy, #about)
   so the Home footer's "Terms · Privacy · About" links land mid-page. No auth,
   no data fetch — everything here is static text describing how the product
   actually behaves; update it when that behaviour changes. */

const P = ({ children }: { children: ReactNode }) => (
  <p className="text-[13.5px] leading-relaxed text-ink-soft [&+&]:mt-3">{children}</p>
);

const LI = ({ children }: { children: ReactNode }) => (
  <li className="text-[13.5px] leading-relaxed text-ink-soft">{children}</li>
);

const UL = ({ children }: { children: ReactNode }) => (
  <ul className="mt-3 list-disc space-y-2 pl-5">{children}</ul>
);

const Strong = ({ children }: { children: ReactNode }) => (
  <strong className="font-semibold text-ink">{children}</strong>
);

export default function LegalPage() {
  // React Router doesn't scroll to hashes on navigation; do it once per hash.
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [hash]);

  return (
    <>
      <header className="sticky top-0 z-10 border-b border-line bg-surface/85 px-8 py-4 backdrop-blur">
        <h1 className="text-[18px] font-semibold leading-tight tracking-tight text-ink">
          Legal
        </h1>
        <p className="mt-0.5 text-[12.5px] text-muted">
          Terms of use, what happens to your data, and what this project is.
        </p>
      </header>

      <main className="mx-auto w-full max-w-[880px] flex-1 px-8 py-7">
        <div className="space-y-7">
          {/* ── Terms ─────────────────────────────────────────────────────── */}
          <section id="terms" className="scroll-mt-20">
            <Card>
              <CardBody>
                <SectionHeading
                  icon={<Scale className="h-4 w-4" />}
                  title="Terms of use"
                  description="Informational product. Not investment advice."
                />
                <P>
                  <Strong>Pharos is an informational product, not investment advice.</Strong>{" "}
                  Its outputs are technology-strategy reads: lifecycle placements, strategist
                  briefings, and portfolio or strategy moves (enter, scale, partner, defend,
                  wait, exit). It never recommends buying or selling any security — that is a
                  deliberate design boundary of the product, not a disclaimer bolted on after
                  the fact. Nothing on this site should be treated as financial, investment,
                  legal, or tax advice, and any decision you make remains yours.
                </P>
                <P>
                  <Strong>No warranty.</Strong> The service is provided as-is, best-effort,
                  with no guarantee of availability, accuracy, or fitness for any purpose.
                </P>
                <P>
                  <Strong>Data may be delayed, incomplete, or wrong.</Strong> Pharos runs
                  entirely on freely available public sources, and its classifications are
                  machine-made from headlines and one-sentence summaries. The measured error
                  rates — including the misses — are published on the{" "}
                  <Link to="/methodology" className="font-medium text-brand hover:underline">
                    Methodology
                  </Link>{" "}
                  page; read them before leaning on any number here.
                </P>
              </CardBody>
            </Card>
          </section>

          {/* ── Privacy ───────────────────────────────────────────────────── */}
          <section id="privacy" className="scroll-mt-20">
            <Card>
              <CardBody>
                <SectionHeading
                  icon={<Lock className="h-4 w-4" />}
                  title="Privacy"
                  description="Short, because there is little to tell."
                />
                <UL>
                  <LI>
                    <Strong>No visitor accounts.</Strong> You can read everything on this site
                    without signing up, and there is nothing to sign up for.
                  </LI>
                  <LI>
                    <Strong>Admin login</Strong> (a single shared operator account) uses a
                    session token kept in the browser's sessionStorage; it dies when the tab
                    closes.
                  </LI>
                  <LI>
                    <Strong>Personalization stays in your browser.</Strong> The optional
                    mandate (your stated focus) and the last-visit timestamp live only in your
                    own browser's localStorage. They are never sent to, or stored on, our
                    servers — clearing your browser storage removes them completely.
                  </LI>
                  <LI>
                    <Strong>No third-party trackers today.</Strong> No analytics scripts, no
                    advertising pixels, no cookies from anyone else. If that ever changes,
                    this page changes first.
                  </LI>
                  <LI>
                    <Strong>Server logs.</Strong> Like almost every web server, ours records
                    standard request metadata (IP address, requested path, timestamp, user
                    agent) for operations and abuse prevention.
                  </LI>
                </UL>
              </CardBody>
            </Card>
          </section>

          {/* ── About ─────────────────────────────────────────────────────── */}
          <section id="about" className="scroll-mt-20">
            <Card>
              <CardBody>
                <SectionHeading
                  icon={<Info className="h-4 w-4" />}
                  title="About"
                  description="What Pharos is, and how it treats the news it reads."
                />
                <P>
                  Pharos is a technology-strategy intelligence tool built as a solo MSc
                  Management-of-Technology project. It reads public technology news through
                  named MOT frameworks — the technology S-curve, diffusion of innovation,
                  technology strategy — and turns that reading into a daily briefing, dated
                  lifecycle placements, and forecasts that are locked when made and graded in
                  the open.
                </P>
                <P>
                  <Strong>News attribution.</Strong> Pharos deliberately stores only a
                  story's headline, a one-sentence summary, and a link — never the article
                  body — and every story shown in the product links back to the original
                  publisher. The journalism is theirs; Pharos's contribution is the
                  classification and the strategic read on top of it.
                </P>
              </CardBody>
            </Card>
          </section>

          <p className="pb-2 text-[12px] text-faint">
            This page describes how the product actually behaves and is updated when that
            behaviour changes.
          </p>
        </div>
      </main>
    </>
  );
}
