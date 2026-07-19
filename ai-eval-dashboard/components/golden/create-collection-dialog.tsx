"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { GOLDEN_METRIC_KEYS } from "@/lib/golden-metrics";
import type { GoldenMetricKey } from "@/types/evaluation";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (input: { name: string; description: string; dimensions: GoldenMetricKey[]; tags: string[] }) => Promise<void>;
  isPending: boolean;
}

export function CreateCollectionDialog({ open, onOpenChange, onCreate, isPending }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [dimensions, setDimensions] = useState<GoldenMetricKey[]>(["toxicity"]);
  const [tags, setTags] = useState("");
  async function submit() {
    await onCreate({ name: name.trim(), description: description.trim(), dimensions, tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean) });
    setName(""); setDescription(""); setDimensions(["toxicity"]); setTags(""); onOpenChange(false);
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>New golden collection</DialogTitle><DialogDescription>Create a reusable, versioned evaluation collection.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <label className="block text-xs font-medium">Name<input aria-label="Collection name" value={name} onChange={(e) => setName(e.target.value)} className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm" /></label>
          <label className="block text-xs font-medium">Description<textarea aria-label="Collection description" value={description} onChange={(e) => setDescription(e.target.value)} className="mt-1 min-h-20 w-full rounded-md border bg-background p-3 text-sm" /></label>
          <fieldset><legend className="text-xs font-medium">Metric dimensions</legend><div className="mt-2 grid grid-cols-2 gap-2">{GOLDEN_METRIC_KEYS.map((metric) => <label key={metric} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={dimensions.includes(metric)} onChange={(e) => setDimensions(e.target.checked ? [...dimensions, metric] : dimensions.filter((item) => item !== metric))} />{metric.replaceAll("_", " ")}</label>)}</div></fieldset>
          <label className="block text-xs font-medium">Tags<input aria-label="Collection tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="Safety, English" className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm" /></label>
          <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!name.trim() || dimensions.length === 0 || isPending} onClick={submit}>Create collection</Button></div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
