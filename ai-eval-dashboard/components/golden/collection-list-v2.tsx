"use client";

import { Archive, Database, Settings2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { GoldenCollection } from "@/types/evaluation";

interface CollectionListProps {
  collections: GoldenCollection[];
  allCollections: GoldenCollection[];
  isLoading: boolean;
  onManage: (id: string) => void;
  onArchive: (collection: GoldenCollection) => void;
}

export function CollectionListV2({ collections, allCollections, isLoading, onManage, onArchive }: CollectionListProps) {
  const counts = new Map<string, number>();
  allCollections.forEach((collection) =>
    collection.memberships.forEach((member) =>
      counts.set(member.exampleId, (counts.get(member.exampleId) ?? 0) + 1)
    )
  );

  if (!isLoading && collections.length === 0) {
    return <div className="flex flex-col items-center py-16 text-center"><Database className="mb-3 h-8 w-8 text-muted-foreground" /><p className="font-medium">No collections yet</p></div>;
  }

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      {collections.map((collection) => {
        const overlap = collection.memberships.filter((member) => (counts.get(member.exampleId) ?? 0) > 1).length;
        const dirty = Boolean(
          collection.latestPublishedAt && collection.updatedAt > collection.latestPublishedAt
        );
        return (
          <Card key={collection.collectionId} className="border-border bg-card">
            <CardContent className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div><h3 className="font-semibold">{collection.name}</h3><p className="mt-1 text-sm text-muted-foreground">{collection.description}</p></div>
                <Badge variant="outline">{collection.status}</Badge>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {collection.dimensions.map((metric) => <Badge key={metric}>{metric.replaceAll("_", " ")}</Badge>)}
                {collection.tags.map((tag) => <Badge key={tag} variant="secondary">{tag}</Badge>)}
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                <span>{collection.memberships.length} examples</span>
                <span>{overlap} overlapping {overlap === 1 ? "example" : "examples"}</span>
                <span>{dirty ? "Draft changes" : collection.latestPublishedVersion ? `v${collection.latestPublishedVersion}` : "Unpublished"}</span>
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={() => onManage(collection.collectionId)} aria-label={`Manage ${collection.name}`}>
                  <Settings2 className="mr-1.5 h-4 w-4" />Manage
                </Button>
                {collection.status !== "archived" && (
                  <Button variant="ghost" size="sm" onClick={() => onArchive(collection)}>
                    <Archive className="mr-1.5 h-4 w-4" />Archive
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
