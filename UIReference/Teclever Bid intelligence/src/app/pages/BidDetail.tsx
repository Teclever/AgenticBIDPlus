import { useState } from "react";
import { useParams, useNavigate } from "react-router";
import {
  ArrowLeft,
  Building2,
  Calendar,
  MapPin,
  Star,
  CheckCircle,
  XCircle,
  FileText,
  Download,
  Send,
  Sparkles
} from "lucide-react";
import { mockBids, mockActivities } from "../lib/mockData";
import { Button } from "../components/ui/Button";
import { format } from "date-fns";

export function BidDetail() {
  const { bidId } = useParams<{ bidId: string }>();
  const navigate = useNavigate();
  const [showAcceptModal, setShowAcceptModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [chatMessage, setChatMessage] = useState("");
  const [chatHistory, setChatHistory] = useState<Array<{ role: 'user' | 'assistant', message: string }>>([]);

  const bid = mockBids.find(b => b.id === bidId);

  if (!bid) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-600">Bid not found</p>
        <Button onClick={() => navigate(-1)} className="mt-4">Go Back</Button>
      </div>
    );
  }

  const handleAccept = () => {
    const userEmail = localStorage.getItem('userEmail') || 'user@teclever.com';
    console.log('Accepted bid:', bid.id, 'by', userEmail);
    setShowAcceptModal(false);
    navigate(-1);
  };

  const handleReject = () => {
    const userEmail = localStorage.getItem('userEmail') || 'user@teclever.com';
    console.log('Rejected bid:', bid.id, 'by', userEmail);
    setShowRejectModal(false);
    navigate(-1);
  };

  const handleSendMessage = () => {
    if (!chatMessage.trim()) return;

    setChatHistory([...chatHistory, { role: 'user', message: chatMessage }]);

    setTimeout(() => {
      const responses: Record<string, string> = {
        'summarize': `This tender is for ${bid.description}. The project involves comprehensive development work with a deadline of ${format(new Date(bid.closeDate), 'MMMM dd, yyyy')}. Key focus areas include modern UI/UX design, technical implementation, and compliance with government standards.`,
        'qualifications': 'Mandatory qualifications include: minimum 5 years of relevant experience, portfolio of similar government projects, technical certifications, and financial stability. The vendor must demonstrate capability to handle projects of this scale.',
        'deliverables': bid.aiSummary?.keyDeliverables?.join(', ') || 'Comprehensive project deliverables as outlined in the RFP document.',
        'technologies': bid.aiSummary?.technicalRequirements?.join(', ') || 'Modern web technologies, cloud infrastructure, and AI/ML capabilities as specified.',
        'timeline': `The project timeline is from ${format(new Date(bid.openDate), 'MMM dd, yyyy')} to ${format(new Date(bid.closeDate), 'MMM dd, yyyy')}. Implementation is expected to be completed within the specified timeframe with regular milestone reviews.`,
        'submission': bid.aiSummary?.submissionRequirements?.join(', ') || 'Technical proposal, financial bid, company credentials, and compliance documents must be submitted before the deadline.'
      };

      const lowerMessage = chatMessage.toLowerCase();
      let response = 'Based on the tender documents, I can help you with specific questions about qualifications, deliverables, technologies, timeline, or submission requirements. Please ask a more specific question.';

      for (const [key, value] of Object.entries(responses)) {
        if (lowerMessage.includes(key)) {
          response = value;
          break;
        }
      }

      setChatHistory(prev => [...prev, { role: 'assistant', message: response }]);
    }, 500);

    setChatMessage("");
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate(-1)}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-3xl font-bold text-gray-900">{bid.id}</h1>
          <p className="text-gray-600 mt-1">{bid.organization}</p>
        </div>
        {bid.status === 'new' && (
          <div className="flex gap-3">
            <Button
              variant="primary"
              onClick={() => setShowAcceptModal(true)}
              className="gap-2"
            >
              <CheckCircle className="w-4 h-4" />
              Accept
            </Button>
            <Button
              variant="danger"
              onClick={() => setShowRejectModal(true)}
              className="gap-2"
            >
              <XCircle className="w-4 h-4" />
              Reject
            </Button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4">Bid Overview</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <InfoField icon={<Building2 />} label="Ministry" value={bid.ministry} />
              <InfoField icon={<Building2 />} label="Department" value={bid.department} />
              <InfoField icon={<Calendar />} label="Open Date" value={format(new Date(bid.openDate), 'MMM dd, yyyy')} />
              <InfoField icon={<Calendar />} label="Close Date" value={format(new Date(bid.closeDate), 'MMM dd, yyyy')} />
              <InfoField icon={<MapPin />} label="Location" value={bid.location} />
              <InfoField icon={<Star />} label="AI Rating" value={`${bid.aiRating}/5`} />
            </div>
            <div className="mt-4 pt-4 border-t border-gray-200">
              <h3 className="text-sm font-medium text-gray-700 mb-2">Description</h3>
              <p className="text-gray-900">{bid.description}</p>
            </div>
          </div>

          <div className="bg-gradient-to-br from-purple-50 to-blue-50 rounded-xl border border-purple-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-5 h-5 text-purple-600" />
              <h2 className="text-xl font-semibold text-gray-900">AI Evaluation</h2>
            </div>
            <div className="space-y-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Star className={`w-5 h-5 ${bid.aiRating >= 4 ? 'text-yellow-500 fill-yellow-500' : 'text-gray-400'}`} />
                  <span className="text-2xl font-bold text-gray-900">{bid.aiRating}/5</span>
                  <span className="text-gray-600">Rating</span>
                </div>
              </div>
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-2">AI Reasoning</h3>
                <p className="text-gray-900">{bid.aiReasoning}</p>
              </div>
            </div>
          </div>

          {bid.aiSummary && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">AI Summary</h2>
              <div className="space-y-4">
                <Section title="Executive Summary" content={bid.aiSummary.executiveSummary} />
                {bid.aiSummary.scopeOverview && (
                  <Section title="Scope Overview" content={bid.aiSummary.scopeOverview} />
                )}
                {bid.aiSummary.keyDeliverables && (
                  <ListSection title="Key Deliverables" items={bid.aiSummary.keyDeliverables} />
                )}
                {bid.aiSummary.technicalRequirements && (
                  <ListSection title="Technical Requirements" items={bid.aiSummary.technicalRequirements} />
                )}
                {bid.aiSummary.eligibilityCriteria && (
                  <ListSection title="Eligibility Criteria" items={bid.aiSummary.eligibilityCriteria} />
                )}
                {bid.aiSummary.submissionRequirements && (
                  <ListSection title="Submission Requirements" items={bid.aiSummary.submissionRequirements} />
                )}
                {bid.aiSummary.risksConsiderations && (
                  <ListSection title="Risks & Considerations" items={bid.aiSummary.risksConsiderations} />
                )}
                {bid.aiSummary.whyPursue && (
                  <Section title="Why Teclever Should Pursue This" content={bid.aiSummary.whyPursue} highlight />
                )}
                {bid.aiSummary.whyNotFit && (
                  <Section title="Why This Is Not a Strong Fit" content={bid.aiSummary.whyNotFit} />
                )}
                {bid.aiSummary.capabilityGaps && (
                  <ListSection title="Capability Gaps" items={bid.aiSummary.capabilityGaps} />
                )}
                {bid.aiSummary.recommendation && (
                  <Section title="Recommendation" content={bid.aiSummary.recommendation} />
                )}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-6">
          {bid.documents && bid.documents.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Tender Documents</h2>
              <div className="space-y-3">
                {bid.documents.map((doc, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
                    <div className="flex items-center gap-3">
                      <FileText className="w-5 h-5 text-gray-600" />
                      <div>
                        <div className="text-sm font-medium text-gray-900">{doc.name}</div>
                        <div className="text-xs text-gray-500">{doc.type}</div>
                      </div>
                    </div>
                    <button className="p-2 hover:bg-white rounded transition-colors">
                      <Download className="w-4 h-4 text-gray-600" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-5 h-5 text-blue-600" />
              <h2 className="text-lg font-semibold text-gray-900">AI Document Assistant</h2>
            </div>
            <div className="space-y-4">
              <div className="h-64 overflow-y-auto space-y-3 p-3 bg-gray-50 rounded-lg">
                {chatHistory.length === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-sm text-gray-500 mb-4">Ask me anything about this tender</p>
                    <div className="space-y-2 text-xs text-gray-400">
                      <p>Try: "Summarize the tender"</p>
                      <p>Or: "What are the qualifications?"</p>
                    </div>
                  </div>
                ) : (
                  chatHistory.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[80%] px-3 py-2 rounded-lg ${
                        msg.role === 'user'
                          ? 'bg-blue-600 text-white'
                          : 'bg-white border border-gray-200 text-gray-900'
                      }`}>
                        <p className="text-sm">{msg.message}</p>
                      </div>
                    </div>
                  ))
                )}
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={chatMessage}
                  onChange={(e) => setChatMessage(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  placeholder="Ask a question..."
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
                />
                <Button onClick={handleSendMessage} size="sm" className="gap-2">
                  <Send className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {showAcceptModal && (
        <Modal
          title="Accept Bid"
          message={`Are you sure you want to accept bid ${bid.id}?`}
          onConfirm={handleAccept}
          onCancel={() => setShowAcceptModal(false)}
          confirmText="Accept"
          confirmVariant="primary"
        />
      )}

      {showRejectModal && (
        <Modal
          title="Reject Bid"
          message={`Are you sure you want to reject bid ${bid.id}?`}
          onConfirm={handleReject}
          onCancel={() => setShowRejectModal(false)}
          confirmText="Reject"
          confirmVariant="danger"
        />
      )}
    </div>
  );
}

function InfoField({ icon, label, value }: { icon: React.ReactNode, label: string, value: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="p-2 bg-gray-100 rounded-lg text-gray-600">
        {icon}
      </div>
      <div>
        <div className="text-xs text-gray-500 mb-0.5">{label}</div>
        <div className="text-sm font-medium text-gray-900">{value}</div>
      </div>
    </div>
  );
}

function Section({ title, content, highlight }: { title: string, content: string, highlight?: boolean }) {
  return (
    <div className={highlight ? 'p-4 bg-green-50 rounded-lg border border-green-200' : ''}>
      <h3 className="text-sm font-semibold text-gray-900 mb-2">{title}</h3>
      <p className="text-sm text-gray-700">{content}</p>
    </div>
  );
}

function ListSection({ title, items }: { title: string, items: string[] }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-900 mb-2">{title}</h3>
      <ul className="space-y-1">
        {items.map((item, idx) => (
          <li key={idx} className="text-sm text-gray-700 flex items-start gap-2">
            <span className="text-blue-600 mt-1">•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface ModalProps {
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirmText: string;
  confirmVariant: 'primary' | 'danger';
}

function Modal({ title, message, onConfirm, onCancel, confirmText, confirmVariant }: ModalProps) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-2">{title}</h3>
        <p className="text-gray-600 mb-6">{message}</p>
        <div className="flex gap-3 justify-end">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant={confirmVariant} onClick={onConfirm}>
            {confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
}
