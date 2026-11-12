/**
 * ConceptTree.tsx — react-arborist SKOS hierarchy viewer.
 *
 * Styled for the Palantir/Glassmorphism dark theme rather than
 * the default light-mode colours.
 */
import React from 'react';
import { Tree } from 'react-arborist';
import type { NodeRendererProps } from 'react-arborist';
import { ChevronRight, ChevronDown, Folder, FileText } from 'lucide-react';
import type { ConceptNode } from './types';

interface ConceptTreeProps {
  data: ConceptNode[];
  onSelectConcept: (concept: ConceptNode) => void;
}

export const ConceptTree: React.FC<ConceptTreeProps> = ({ data, onSelectConcept }) => {
  return (
    <div style={{
      height: '100%', width: '100%',
      backgroundColor: 'transparent',
      overflow: 'hidden',
    }}>
      <Tree
        data={data}
        idAccessor="uri"
        width="100%"
        height={600}
        indent={24}
        rowHeight={36}
        childrenAccessor="children"
      >
        {(nodeProps: NodeRendererProps<ConceptNode>) => {
          const { node, style, dragHandle } = nodeProps;
          const isFolder = node.children && node.children.length > 0;

          return (
            <div
              ref={dragHandle}
              onClick={() => {
                node.toggle();
                onSelectConcept(node.data);
              }}
              style={{
                ...style,
                display: 'flex',
                alignItems: 'center',
                padding: '0 8px',
                cursor: 'pointer',
                backgroundColor: node.isSelected
                  ? 'rgba(0, 82, 217,0.12)'
                  : 'transparent',
                userSelect: 'none',
                borderBottom: '1px solid rgba(0, 0, 0, 0.04)',
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => {
                if (!node.isSelected) {
                  (e.currentTarget as HTMLDivElement).style.background = 'rgba(0, 82, 217,0.06)';
                }
              }}
              onMouseLeave={(e) => {
                if (!node.isSelected) {
                  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
                }
              }}
            >
              <span style={{ width: 20, display: 'flex', justifyContent: 'center' }}>
                {isFolder ? (
                  node.isOpen
                    ? <ChevronDown size={14} color="rgba(0, 0, 0, 0.6)" />
                    : <ChevronRight size={14} color="rgba(0, 0, 0, 0.6)" />
                ) : null}
              </span>

              <span style={{ marginRight: 8, display: 'flex', alignItems: 'center' }}>
                {isFolder
                  ? <Folder size={14} color="#5e3ab8" />
                  : <FileText size={14} color="rgba(0, 0, 0, 0.26)" />
                }
              </span>

              <span style={{
                fontSize: 13, color: 'rgba(0, 0, 0, 0.85)',
                whiteSpace: 'nowrap', overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {node.data.pref_label}
              </span>
            </div>
          );
        }}
      </Tree>
    </div>
  );
};