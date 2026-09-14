import { ScanSearch } from 'lucide-react';

import { ReservedModule } from '../../components/ReservedModule';

export function IntelligencePage() {
  return (
    <ReservedModule
      eyebrow="研究 / 情报中心"
      title="情报中心"
      description="未来用于汇总可能影响A股行情的每日情报。"
      purpose="该模块今后会将市场、公司、行业、政策、宏观和全球事件研究整理为可长期保存、来源可追溯的研究成果。"
      icon={ScanSearch}
    />
  );
}
