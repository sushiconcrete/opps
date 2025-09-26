# OPP Agent: Mock to Real API Integration

## Overview
Transition the OPP Agent frontend from mock data (`api.ts`) to real backend integration (`app.py`) while maintaining the current UI/UX design. *Only* add new UI elements when implementing new functionalities like archive system.

## Current State Analysis

### Frontend (`image-combiner.tsx`)
- **Mock streaming**: Uses `streamMockRun()` for fake progress updates
- **Local state management**: Monitors, competitors, changes stored in React state
- **No authentication**: Direct access to analysis features
- **Mock data flow**: `tenant` → `competitors` → `changes` stages

### Backend (`app.py`)
- **Existing endpoints**: `/api/analyze`, `/api/status/{task_id}`
- **Database models**: `User`, `AnalysisTask`, `Tenant`, `Competitor`, `ChangeDetectionCache`
- **OAuth ready**: Google/GitHub authentication configured
- **Real analysis pipeline**: Tenant analysis → Competitor finding → Change detection

## Integration Requirements

### 1. Authentication Integration
- **Replace**: Direct access with OAuth-protected routes
- **Add**: Login/logout flow using existing backend OAuth
- **Maintain**: Current UI design (no visual changes)
- **Trigger**: Login page when "Find" clicked without authentication

### 2. Real-time Progress Tracking (reflected by current shimmer text, e.g. Building company overview..., finding competitors etc. when each stage is processing.)
- **Replace**: `streamMockRun()` with WebSocket/SSE to backend
- **Maintain**: Current stage progression UI (`tenant` → `competitors` → `changes`)
- **Add**: Real progress percentages from backend analysis
- **Keep**: Existing loading states and error handling

### 3. Database Persistence
- **Replace**: Local React state with API calls
- **Implement**: Monitor CRUD operations (create, switch, delete)
- **Add**: Competitor tracking/untracking with database persistence
- **Maintain**: Current monitor dropdown and competitor management UI

### 4. Change Detection & Unread Management
- **Replace**: Mock change data with real change detection cache
- **Implement**: Read/unread states with database persistence
- **Add**: Bulk operations (mark all as read)
- **Keep**: Current change radar UI design

### 5. Archive System (New Feature)
- **Add**: Archive functionality for completed analyses
- **Create**: New UI section for browsing archived analyses
- **Implement**: Archive metadata and search capabilities

## Technical Implementation

### Backend API Extensions
```python
# Authentication (existing)
POST /api/auth/login
GET  /api/auth/me

# Monitor Management (new)
GET    /api/monitors
POST   /api/monitors
DELETE /api/monitors/{id}

# Real-time Analysis (extend existing)
WebSocket /ws/analysis/{task_id}
GET       /api/analyze/{task_id}/progress

# Competitor Management (new)
POST   /api/competitors/{id}/track
DELETE /api/competitors/{id}/untrack

# Change Detection (extend existing)
POST   /api/changes/{id}/read
POST   /api/changes/bulk-read

# Archive System (new)
GET    /api/archives
POST   /api/archives
```

### Frontend Changes
- **Minimal UI changes**: Keep existing design and layout
- **Replace API calls**: Mock functions → Real API endpoints
- **Add authentication**: Login flow integration
- **New archive UI**: Additional section for archived analyses
- **Maintain state**: Same React state structure, different data source

### Database Schema Updates
- **User-Monitor relationships**: Link monitors to authenticated users
- **Competitor tracking**: User-specific competitor tracking states
- **Change read states**: Per-user read/unread tracking
- **Archive tables**: Store completed analysis snapshots

## Migration Strategy

### Phase 1: Authentication
1. Integrate OAuth flow with existing backend
2. Add auth guards to protected routes
3. Implement session management
4. **UI Impact**: Login page, no changes to main interface

### Phase 2: Real API Integration
1. Replace `streamMockRun()` with WebSocket connection
2. Implement real monitor CRUD operations
3. Add competitor tracking/untracking
4. **UI Impact**: None (same interface, real data)

### Phase 3: Change Detection & Archive
1. Implement real change detection with unread management
2. Add archive system with new UI section
3. Implement bulk operations
4. **UI Impact**: New archive section, enhanced change management

## Success Criteria
- ✅ **Zero visual changes** to existing UI (except archive section)
- ✅ **Seamless authentication** with OAuth providers
- ✅ **Real-time progress** with accurate stage updates
- ✅ **Persistent data** across browser sessions
- ✅ **Complete feature parity** with current mock implementation
- ✅ **New archive functionality** with dedicated UI
