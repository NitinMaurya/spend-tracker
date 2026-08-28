import { PlanScreen } from "@/components/plan-screen";
import { EvaluatePanel } from "@/components/evaluate-panel";
import { Aside, PageTitle, SectionTitle } from "@/components/ui";

export const dynamic = "force-dynamic";

/**
 * Plan — the product's primary output.
 *
 * This used to be an essay explaining why a plan could not be produced. The
 * thing actually blocking it was a missing input only a person can supply: the
 * mapping from each quoted reward rate to the categories it covers. So the page
 * now asks for that, then shows the plan.
 */
export default function PlanPage() {
  return (
    <main id="main" className="mx-auto flex max-w-[70rem] flex-col gap-9 px-6 pb-16 pt-8">
      <PageTitle sub="What to put on which card, and what to leave exactly where it is — priced against your own statements, using only rates you have confirmed against the terms they came from.">
        What to put on which card
      </PageTitle>

      <PlanScreen />

      <section className="flex flex-col gap-4">
        <SectionTitle aside="drop a Key Facts Statement for a card you do not hold">
          Is a card worth getting?
        </SectionTitle>
        <EvaluatePanel />
      </section>

      <Aside summary="Why two numbers are always reported, and what “routable” excludes">
        <p>
          A plan reports both what your spending earns unchanged and what it would earn if you
          followed the plan. Collapsing them into a single headline overstates every card, because
          the higher figure quietly assumes you reorganise your spending perfectly and keep doing
          it. The gap between them is what the effort is worth — and when the gap is small, the
          honest recommendation is to leave things alone.
        </p>
        <p>
          Only routable purchase spend is ever moved. Merchant-locked charges, direct debits and
          acceptance-limited rows stay where they are, because moving them is not something you can
          actually do. Where a rule cannot be evaluated — an exclusion that is undetectable from
          statement text, or two sources that disagree — the spend is held out of both figures
          rather than assumed in the card&rsquo;s favour.
        </p>
      </Aside>
    </main>
  );
}
