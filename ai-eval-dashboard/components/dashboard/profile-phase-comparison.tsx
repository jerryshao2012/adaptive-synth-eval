import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ProfilePeriodSummary } from "@/lib/aggregation";

interface ProfilePhaseComparisonProps {
  summaries: ProfilePeriodSummary[];
}

function percent(value: number | null): string {
  return value === null ? "—" : `${value}%`;
}

export function ProfilePhaseComparison({
  summaries,
}: ProfilePhaseComparisonProps) {
  if (summaries.length === 0) return null;

  const failRates = summaries.map((summary) => summary.failRate);
  const highestFailRate = Math.max(...failRates);
  const hasFailRateDifference = highestFailRate > Math.min(...failRates);
  const toxicityScores = summaries.flatMap((summary) =>
    summary.toxicitySafetyScore === null
      ? []
      : [summary.toxicitySafetyScore]
  );
  const lowestToxicityScore =
    toxicityScores.length > 0 ? Math.min(...toxicityScores) : null;
  const hasToxicityDifference =
    toxicityScores.length > 1 &&
    lowestToxicityScore !== Math.max(...toxicityScores);

  return (
    <Card className="mb-6 border-border bg-card">
      <CardHeader>
        <CardTitle>Phase comparison</CardTitle>
        <CardDescription>
          Repeated daily profile windows grouped by phase. Toxicity safety is
          the safety score; lower is worse.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-215 text-left text-xs">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Phase</th>
                <th className="px-3 py-2 font-medium">Mode + daily hours</th>
                <th className="px-3 py-2 text-right font-medium">
                  Evaluations
                </th>
                <th className="px-3 py-2 text-right font-medium">
                  Pass / fail
                </th>
                <th className="px-3 py-2 text-right font-medium">
                  Toxicity safety
                </th>
                <th className="px-3 py-2 text-right font-medium">
                  Safety avg
                </th>
                <th className="px-3 py-2 text-right font-medium">
                  Performance avg
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {summaries.map((summary) => {
                const hasComparativelyHigherFailure =
                  hasFailRateDifference && summary.failRate === highestFailRate;
                const hasComparativelyLowerToxicity =
                  hasToxicityDifference &&
                  summary.toxicitySafetyScore === lowestToxicityScore;

                return (
                  <tr key={summary.periodId} className="hover:bg-muted/30">
                    <td className="px-3 py-2.5">
                      <Badge variant="outline">{summary.periodId}</Badge>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="font-medium text-foreground">
                        {summary.modeLabel}
                      </div>
                      <div className="mt-0.5 text-muted-foreground">
                        {summary.timeLabel}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                      {summary.evaluationCount}
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2.5 text-right font-mono tabular-nums",
                        hasComparativelyHigherFailure &&
                          "bg-destructive/5 text-destructive"
                      )}
                      aria-label={
                        hasComparativelyHigherFailure
                          ? `${summary.passRate}% pass / ${summary.failRate}% fail; comparatively higher fail rate`
                          : undefined
                      }
                    >
                      {summary.passRate}% / {summary.failRate}%
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2.5 text-right font-mono tabular-nums",
                        hasComparativelyLowerToxicity &&
                          "bg-destructive/5 text-destructive"
                      )}
                      aria-label={
                        hasComparativelyLowerToxicity
                          ? `${percent(summary.toxicitySafetyScore)} toxicity safety; comparatively lower toxicity safety score`
                          : undefined
                      }
                    >
                      {percent(summary.toxicitySafetyScore)}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                      {percent(summary.safetyAverage)}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                      {percent(summary.performanceAverage)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
