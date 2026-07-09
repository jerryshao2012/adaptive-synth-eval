"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface CreateDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (name: string, version: string) => void;
  isPending: boolean;
}

export function CreateDatasetDialog({
  open,
  onOpenChange,
  onCreate,
  isPending,
}: CreateDatasetDialogProps) {
  const [name, setName] = useState("");
  const [version, setVersion] = useState("v1.0");

  function handleCreate() {
    if (!name.trim() || !version.trim()) return;
    onCreate(name.trim(), version.trim());
    setName("");
    setVersion("v1.0");
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md border-border bg-card text-foreground">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">
            Create Golden Dataset
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            A golden dataset collects reviewed evaluation records for model
            benchmarking and fine-tuning. Records are selected from completed
            review runs.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          <div>
            <label className="text-xs font-medium text-foreground mb-1.5 block">
              Dataset Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Production Safety Golden Set"
              className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50 placeholder:text-muted-foreground"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-foreground mb-1.5 block">
              Version
            </label>
            <input
              type="text"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="v1.0"
              className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm font-mono text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50 placeholder:text-muted-foreground"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleCreate}
            disabled={!name.trim() || !version.trim() || isPending}
          >
            Create Dataset
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
