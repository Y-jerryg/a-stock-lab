import { ScanSearch } from 'lucide-react';

import { ReservedModule } from '../../components/ReservedModule';

export function IntelligencePage() {
  return (
    <ReservedModule
      eyebrow="Research / Intelligence"
      title="Intelligence"
      description="The future daily intelligence surface for market-moving information relevant to A-shares."
      purpose="This boundary will eventually organize market, company, industry, policy, macro, and global-event research into durable, source-aware artifacts."
      icon={ScanSearch}
    />
  );
}
