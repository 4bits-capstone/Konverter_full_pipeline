import {
  fastApiApprovalService,
  fastApiDocumentService,
  fastApiMetadataService,
  fastApiPublicationService,
  fastApiReviewService,
} from './fastApi'

export const documentService = fastApiDocumentService
export const reviewService = fastApiReviewService
export const metadataService = fastApiMetadataService
export const approvalService = fastApiApprovalService
export const publicationService = fastApiPublicationService
