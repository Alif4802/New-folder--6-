import { CurriculumScopeNode } from '../types/api';

export type CheckState = 'checked' | 'unchecked' | 'indeterminate';

export interface TreeMaps {
  nodeMap: Map<string, CurriculumScopeNode>;
  parentMap: Map<string, string>;
  descendantsMap: Map<string, string[]>;
  ancestorsMap: Map<string, string[]>;
  allNodeIds: string[];
}

/**
 * Builds lookup maps for arbitrary depth trees in a single recursive pass.
 */
export function buildTreeMaps(nodes: CurriculumScopeNode[]): TreeMaps {
  const nodeMap = new Map<string, CurriculumScopeNode>();
  const parentMap = new Map<string, string>();
  const descendantsMap = new Map<string, string[]>();
  const ancestorsMap = new Map<string, string[]>();
  const allNodeIds: string[] = [];

  function traverse(node: CurriculumScopeNode, parentId?: string, currentAncestors: string[] = []) {
    nodeMap.set(node.id, node);
    allNodeIds.push(node.id);

    if (parentId) {
      parentMap.set(node.id, parentId);
    }
    ancestorsMap.set(node.id, currentAncestors);

    const descIds: string[] = [];
    if (node.children && node.children.length > 0) {
      const nextAncestors = [node.id, ...currentAncestors];
      for (const child of node.children) {
        traverse(child, node.id, nextAncestors);
        descIds.push(child.id);
        const childDescs = descendantsMap.get(child.id) || [];
        descIds.push(...childDescs);
      }
    }
    descendantsMap.set(node.id, descIds);
  }

  for (const root of nodes) {
    traverse(root);
  }

  return {
    nodeMap,
    parentMap,
    descendantsMap,
    ancestorsMap,
    allNodeIds,
  };
}

/**
 * Evaluates the tri-state check status of a given node.
 */
export function getNodeCheckState(
  nodeId: string,
  selectedIds: Set<string>,
  descendantsMap: Map<string, string[]>
): CheckState {
  const descIds = descendantsMap.get(nodeId) || [];

  if (descIds.length === 0) {
    return selectedIds.has(nodeId) ? 'checked' : 'unchecked';
  }

  let selectedDescendantCount = 0;
  for (const did of descIds) {
    if (selectedIds.has(did)) {
      selectedDescendantCount++;
    }
  }

  if (selectedDescendantCount === descIds.length && descIds.length > 0) {
    return 'checked';
  }

  if (selectedDescendantCount > 0) {
    return 'indeterminate';
  }

  // If no descendants are selected, check if node itself was directly selected
  if (selectedIds.has(nodeId)) {
    return 'checked';
  }

  return 'unchecked';
}

/**
 * Computes the new Set of selected IDs when a node's checkbox is toggled with cascade semantics.
 */
export function toggleNodeCascade(
  nodeId: string,
  currentSelected: Set<string>,
  treeMaps: TreeMaps
): Set<string> {
  const { descendantsMap, ancestorsMap } = treeMaps;
  const nextSelected = new Set(currentSelected);

  const currentState = getNodeCheckState(nodeId, nextSelected, descendantsMap);
  const descIds = descendantsMap.get(nodeId) || [];
  const ancestors = ancestorsMap.get(nodeId) || [];

  if (currentState === 'checked') {
    // Deselect node and all its descendants
    nextSelected.delete(nodeId);
    for (const did of descIds) {
      nextSelected.delete(did);
    }
    // Also remove ancestors from selected set since not all their descendants are checked
    for (const ancId of ancestors) {
      nextSelected.delete(ancId);
    }
  } else {
    // Select node and all its descendants (for 'unchecked' or 'indeterminate')
    nextSelected.add(nodeId);
    for (const did of descIds) {
      nextSelected.add(did);
    }
    // Check if any ancestor now has ALL of its descendants selected
    for (const ancId of ancestors) {
      const ancDescs = descendantsMap.get(ancId) || [];
      const allAncDescsSelected = ancDescs.every((id) => nextSelected.has(id));
      if (allAncDescsSelected) {
        nextSelected.add(ancId);
      } else {
        nextSelected.delete(ancId);
      }
    }
  }

  return nextSelected;
}

/**
 * Calculates effective top-level scopes (ignoring descendants if ancestor is selected).
 */
export function getEffectiveTopLevelScopeCount(
  selectedIds: Set<string>,
  treeMaps: TreeMaps
): number {
  if (selectedIds.size === 0) return 0;

  let count = 0;
  for (const id of selectedIds) {
    const ancestors = treeMaps.ancestorsMap.get(id) || [];
    const hasSelectedAncestor = ancestors.some((ancId) => selectedIds.has(ancId));
    if (!hasSelectedAncestor) {
      count++;
    }
  }
  return count;
}
