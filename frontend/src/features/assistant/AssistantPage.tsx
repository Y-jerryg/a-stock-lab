import { Bot } from 'lucide-react';

import { ReservedModule } from '../../components/ReservedModule';

export function AssistantPage() {
  return (
    <ReservedModule
      eyebrow="人工智能 / 研究助手"
      title="AI 研究助手"
      description="未来基于平台自身研究成果提供协助，而不是与业务脱节的通用聊天机器人。"
      purpose="该模块将使用尾盘雷达、情报中心和量化实验室生成的版本化研究成果。模型访问和密钥始终只保留在后端。"
      icon={Bot}
    />
  );
}
