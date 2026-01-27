"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.AthenaStack = void 0;
const cdk = require("aws-cdk-lib");
const athena = require("aws-cdk-lib/aws-athena");
class AthenaStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        // Athena Workgroup
        this.workgroup = new athena.CfnWorkGroup(this, 'Workgroup', {
            name: 'cx-analytics-workgroup',
            workGroupConfiguration: {
                resultConfiguration: {
                    outputLocation: `s3://${props.dataLakeBucket.bucketName}/athena-results/`,
                },
                enforceWorkGroupConfiguration: true,
                publishCloudWatchMetricsEnabled: true,
            },
        });
        // Customer Health View
        const customerHealthView = new athena.CfnNamedQuery(this, 'CustomerHealthView', {
            database: props.glueDatabase.ref,
            queryString: `
CREATE OR REPLACE VIEW customer_health AS
SELECT 
  customer_id,
  user_id,
  total_revenue,
  avg_satisfaction_score,
  total_cases,
  open_cases,
  total_vehicles,
  total_service_spend,
  total_service_appointments,
  opportunity_count,
  ROUND(
    (COALESCE(avg_satisfaction_score, 50) * 0.25) +
    (CASE WHEN open_cases = 0 THEN 80 ELSE 30 END * 0.20) +
    (CASE WHEN total_vehicles >= 2 THEN 90 ELSE 70 END * 0.15) +
    (CASE WHEN total_service_appointments > 5 THEN 80 ELSE 50 END * 0.30) +
    (100 * 0.10)
  , 2) as health_score,
  CASE 
    WHEN health_score >= 70 THEN 'Healthy'
    WHEN health_score >= 50 THEN 'Needs Attention'
    WHEN health_score >= 30 THEN 'At-Risk'
    ELSE 'Critical'
  END as health_segment
FROM customer_360
      `,
            name: 'customer_health_view',
            workGroup: this.workgroup.name,
        });
        customerHealthView.addDependency(this.workgroup);
        // Churn Prediction View
        const churnPredictionView = new athena.CfnNamedQuery(this, 'ChurnPredictionView', {
            database: props.glueDatabase.ref,
            queryString: `
CREATE OR REPLACE VIEW churn_prediction AS
SELECT 
  customer_id,
  health_score,
  health_segment,
  total_revenue,
  CASE 
    WHEN health_score < 25 THEN 'Critical Risk'
    WHEN health_score < 30 THEN 'High Risk'
    WHEN health_score < 35 THEN 'Medium Risk'
    ELSE 'Low Risk'
  END as churn_risk,
  CASE 
    WHEN health_score < 25 THEN 0.70
    WHEN health_score < 30 THEN 0.45
    WHEN health_score < 35 THEN 0.20
    ELSE 0.05
  END as churn_probability,
  CASE WHEN health_score < 35 THEN 1 ELSE 0 END as churn_indicator,
  total_revenue * CASE 
    WHEN health_score < 25 THEN 0.70
    WHEN health_score < 30 THEN 0.45
    WHEN health_score < 35 THEN 0.20
    ELSE 0.05
  END as expected_loss
FROM customer_health
WHERE health_score < 35
      `,
            name: 'churn_prediction_view',
            workGroup: this.workgroup.name,
        });
        churnPredictionView.addDependency(this.workgroup);
        // CLV Analysis View
        const clvAnalysisView = new athena.CfnNamedQuery(this, 'CLVAnalysisView', {
            database: props.glueDatabase.ref,
            queryString: `
CREATE OR REPLACE VIEW clv_analysis AS
SELECT 
  customer_id,
  total_revenue * 3.5 as actual_clv,
  total_revenue as annual_value,
  total_revenue * 4.2 as predicted_clv_3yr,
  health_score,
  health_segment,
  total_revenue,
  CASE 
    WHEN total_revenue >= 10000 THEN 'B2B Fleet'
    WHEN total_revenue >= 4000 THEN 'B2C Premium'
    WHEN total_revenue >= 2000 THEN 'B2C Standard'
    ELSE 'B2C Entry'
  END as customer_type,
  CASE 
    WHEN total_revenue >= 10000 THEN 'Enterprise'
    WHEN total_revenue >= 4000 THEN 'Premium'
    WHEN total_revenue >= 2000 THEN 'Standard'
    ELSE 'Entry'
  END as value_tier
FROM customer_health
      `,
            name: 'clv_analysis_view',
            workGroup: this.workgroup.name,
        });
        clvAnalysisView.addDependency(this.workgroup);
        // Revenue at Risk View
        const revenueAtRiskView = new athena.CfnNamedQuery(this, 'RevenueAtRiskView', {
            database: props.glueDatabase.ref,
            queryString: `
CREATE OR REPLACE VIEW revenue_at_risk AS
SELECT 
  health_segment,
  COUNT(*) as customer_count,
  SUM(total_revenue) as total_revenue,
  SUM(CASE WHEN health_score < 40 THEN total_revenue ELSE 0 END) as revenue_at_risk,
  ROUND(
    SUM(CASE WHEN health_score < 40 THEN total_revenue ELSE 0 END) * 100.0 / 
    NULLIF(SUM(total_revenue), 0), 2
  ) as pct_at_risk
FROM customer_health
GROUP BY health_segment
      `,
            name: 'revenue_at_risk_view',
            workGroup: this.workgroup.name,
        });
        revenueAtRiskView.addDependency(this.workgroup);
        new cdk.CfnOutput(this, 'AthenaWorkgroup', {
            value: this.workgroup.name,
            description: 'Athena Workgroup Name',
        });
    }
}
exports.AthenaStack = AthenaStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXRoZW5hLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXRoZW5hLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7OztBQUFBLG1DQUFtQztBQUNuQyxpREFBaUQ7QUFVakQsTUFBYSxXQUFZLFNBQVEsR0FBRyxDQUFDLEtBQUs7SUFHeEMsWUFBWSxLQUFnQixFQUFFLEVBQVUsRUFBRSxLQUF1QjtRQUMvRCxLQUFLLENBQUMsS0FBSyxFQUFFLEVBQUUsRUFBRSxLQUFLLENBQUMsQ0FBQztRQUV4QixtQkFBbUI7UUFDbkIsSUFBSSxDQUFDLFNBQVMsR0FBRyxJQUFJLE1BQU0sQ0FBQyxZQUFZLENBQUMsSUFBSSxFQUFFLFdBQVcsRUFBRTtZQUMxRCxJQUFJLEVBQUUsd0JBQXdCO1lBQzlCLHNCQUFzQixFQUFFO2dCQUN0QixtQkFBbUIsRUFBRTtvQkFDbkIsY0FBYyxFQUFFLFFBQVEsS0FBSyxDQUFDLGNBQWMsQ0FBQyxVQUFVLGtCQUFrQjtpQkFDMUU7Z0JBQ0QsNkJBQTZCLEVBQUUsSUFBSTtnQkFDbkMsK0JBQStCLEVBQUUsSUFBSTthQUN0QztTQUNGLENBQUMsQ0FBQztRQUVILHVCQUF1QjtRQUN2QixNQUFNLGtCQUFrQixHQUFHLElBQUksTUFBTSxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsb0JBQW9CLEVBQUU7WUFDOUUsUUFBUSxFQUFFLEtBQUssQ0FBQyxZQUFZLENBQUMsR0FBRztZQUNoQyxXQUFXLEVBQUU7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztPQTJCWjtZQUNELElBQUksRUFBRSxzQkFBc0I7WUFDNUIsU0FBUyxFQUFFLElBQUksQ0FBQyxTQUFTLENBQUMsSUFBSTtTQUMvQixDQUFDLENBQUM7UUFDSCxrQkFBa0IsQ0FBQyxhQUFhLENBQUMsSUFBSSxDQUFDLFNBQVMsQ0FBQyxDQUFDO1FBRWpELHdCQUF3QjtRQUN4QixNQUFNLG1CQUFtQixHQUFHLElBQUksTUFBTSxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUscUJBQXFCLEVBQUU7WUFDaEYsUUFBUSxFQUFFLEtBQUssQ0FBQyxZQUFZLENBQUMsR0FBRztZQUNoQyxXQUFXLEVBQUU7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7T0E0Qlo7WUFDRCxJQUFJLEVBQUUsdUJBQXVCO1lBQzdCLFNBQVMsRUFBRSxJQUFJLENBQUMsU0FBUyxDQUFDLElBQUk7U0FDL0IsQ0FBQyxDQUFDO1FBQ0gsbUJBQW1CLENBQUMsYUFBYSxDQUFDLElBQUksQ0FBQyxTQUFTLENBQUMsQ0FBQztRQUVsRCxvQkFBb0I7UUFDcEIsTUFBTSxlQUFlLEdBQUcsSUFBSSxNQUFNLENBQUMsYUFBYSxDQUFDLElBQUksRUFBRSxpQkFBaUIsRUFBRTtZQUN4RSxRQUFRLEVBQUUsS0FBSyxDQUFDLFlBQVksQ0FBQyxHQUFHO1lBQ2hDLFdBQVcsRUFBRTs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7T0F1Qlo7WUFDRCxJQUFJLEVBQUUsbUJBQW1CO1lBQ3pCLFNBQVMsRUFBRSxJQUFJLENBQUMsU0FBUyxDQUFDLElBQUk7U0FDL0IsQ0FBQyxDQUFDO1FBQ0gsZUFBZSxDQUFDLGFBQWEsQ0FBQyxJQUFJLENBQUMsU0FBUyxDQUFDLENBQUM7UUFFOUMsdUJBQXVCO1FBQ3ZCLE1BQU0saUJBQWlCLEdBQUcsSUFBSSxNQUFNLENBQUMsYUFBYSxDQUFDLElBQUksRUFBRSxtQkFBbUIsRUFBRTtZQUM1RSxRQUFRLEVBQUUsS0FBSyxDQUFDLFlBQVksQ0FBQyxHQUFHO1lBQ2hDLFdBQVcsRUFBRTs7Ozs7Ozs7Ozs7OztPQWFaO1lBQ0QsSUFBSSxFQUFFLHNCQUFzQjtZQUM1QixTQUFTLEVBQUUsSUFBSSxDQUFDLFNBQVMsQ0FBQyxJQUFJO1NBQy9CLENBQUMsQ0FBQztRQUNILGlCQUFpQixDQUFDLGFBQWEsQ0FBQyxJQUFJLENBQUMsU0FBUyxDQUFDLENBQUM7UUFFaEQsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxpQkFBaUIsRUFBRTtZQUN6QyxLQUFLLEVBQUUsSUFBSSxDQUFDLFNBQVMsQ0FBQyxJQUFLO1lBQzNCLFdBQVcsRUFBRSx1QkFBdUI7U0FDckMsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztDQUNGO0FBdEpELGtDQXNKQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgKiBhcyBhdGhlbmEgZnJvbSAnYXdzLWNkay1saWIvYXdzLWF0aGVuYSc7XG5pbXBvcnQgKiBhcyBzMyBmcm9tICdhd3MtY2RrLWxpYi9hd3MtczMnO1xuaW1wb3J0ICogYXMgZ2x1ZSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZ2x1ZSc7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGludGVyZmFjZSBBdGhlbmFTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICBkYXRhTGFrZUJ1Y2tldDogczMuSUJ1Y2tldDtcbiAgZ2x1ZURhdGFiYXNlOiBnbHVlLkNmbkRhdGFiYXNlO1xufVxuXG5leHBvcnQgY2xhc3MgQXRoZW5hU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgd29ya2dyb3VwOiBhdGhlbmEuQ2ZuV29ya0dyb3VwO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBBdGhlbmFTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICAvLyBBdGhlbmEgV29ya2dyb3VwXG4gICAgdGhpcy53b3JrZ3JvdXAgPSBuZXcgYXRoZW5hLkNmbldvcmtHcm91cCh0aGlzLCAnV29ya2dyb3VwJywge1xuICAgICAgbmFtZTogJ2N4LWFuYWx5dGljcy13b3JrZ3JvdXAnLFxuICAgICAgd29ya0dyb3VwQ29uZmlndXJhdGlvbjoge1xuICAgICAgICByZXN1bHRDb25maWd1cmF0aW9uOiB7XG4gICAgICAgICAgb3V0cHV0TG9jYXRpb246IGBzMzovLyR7cHJvcHMuZGF0YUxha2VCdWNrZXQuYnVja2V0TmFtZX0vYXRoZW5hLXJlc3VsdHMvYCxcbiAgICAgICAgfSxcbiAgICAgICAgZW5mb3JjZVdvcmtHcm91cENvbmZpZ3VyYXRpb246IHRydWUsXG4gICAgICAgIHB1Ymxpc2hDbG91ZFdhdGNoTWV0cmljc0VuYWJsZWQ6IHRydWUsXG4gICAgICB9LFxuICAgIH0pO1xuXG4gICAgLy8gQ3VzdG9tZXIgSGVhbHRoIFZpZXdcbiAgICBjb25zdCBjdXN0b21lckhlYWx0aFZpZXcgPSBuZXcgYXRoZW5hLkNmbk5hbWVkUXVlcnkodGhpcywgJ0N1c3RvbWVySGVhbHRoVmlldycsIHtcbiAgICAgIGRhdGFiYXNlOiBwcm9wcy5nbHVlRGF0YWJhc2UucmVmLFxuICAgICAgcXVlcnlTdHJpbmc6IGBcbkNSRUFURSBPUiBSRVBMQUNFIFZJRVcgY3VzdG9tZXJfaGVhbHRoIEFTXG5TRUxFQ1QgXG4gIGN1c3RvbWVyX2lkLFxuICB1c2VyX2lkLFxuICB0b3RhbF9yZXZlbnVlLFxuICBhdmdfc2F0aXNmYWN0aW9uX3Njb3JlLFxuICB0b3RhbF9jYXNlcyxcbiAgb3Blbl9jYXNlcyxcbiAgdG90YWxfdmVoaWNsZXMsXG4gIHRvdGFsX3NlcnZpY2Vfc3BlbmQsXG4gIHRvdGFsX3NlcnZpY2VfYXBwb2ludG1lbnRzLFxuICBvcHBvcnR1bml0eV9jb3VudCxcbiAgUk9VTkQoXG4gICAgKENPQUxFU0NFKGF2Z19zYXRpc2ZhY3Rpb25fc2NvcmUsIDUwKSAqIDAuMjUpICtcbiAgICAoQ0FTRSBXSEVOIG9wZW5fY2FzZXMgPSAwIFRIRU4gODAgRUxTRSAzMCBFTkQgKiAwLjIwKSArXG4gICAgKENBU0UgV0hFTiB0b3RhbF92ZWhpY2xlcyA+PSAyIFRIRU4gOTAgRUxTRSA3MCBFTkQgKiAwLjE1KSArXG4gICAgKENBU0UgV0hFTiB0b3RhbF9zZXJ2aWNlX2FwcG9pbnRtZW50cyA+IDUgVEhFTiA4MCBFTFNFIDUwIEVORCAqIDAuMzApICtcbiAgICAoMTAwICogMC4xMClcbiAgLCAyKSBhcyBoZWFsdGhfc2NvcmUsXG4gIENBU0UgXG4gICAgV0hFTiBoZWFsdGhfc2NvcmUgPj0gNzAgVEhFTiAnSGVhbHRoeSdcbiAgICBXSEVOIGhlYWx0aF9zY29yZSA+PSA1MCBUSEVOICdOZWVkcyBBdHRlbnRpb24nXG4gICAgV0hFTiBoZWFsdGhfc2NvcmUgPj0gMzAgVEhFTiAnQXQtUmlzaydcbiAgICBFTFNFICdDcml0aWNhbCdcbiAgRU5EIGFzIGhlYWx0aF9zZWdtZW50XG5GUk9NIGN1c3RvbWVyXzM2MFxuICAgICAgYCxcbiAgICAgIG5hbWU6ICdjdXN0b21lcl9oZWFsdGhfdmlldycsXG4gICAgICB3b3JrR3JvdXA6IHRoaXMud29ya2dyb3VwLm5hbWUsXG4gICAgfSk7XG4gICAgY3VzdG9tZXJIZWFsdGhWaWV3LmFkZERlcGVuZGVuY3kodGhpcy53b3JrZ3JvdXApO1xuXG4gICAgLy8gQ2h1cm4gUHJlZGljdGlvbiBWaWV3XG4gICAgY29uc3QgY2h1cm5QcmVkaWN0aW9uVmlldyA9IG5ldyBhdGhlbmEuQ2ZuTmFtZWRRdWVyeSh0aGlzLCAnQ2h1cm5QcmVkaWN0aW9uVmlldycsIHtcbiAgICAgIGRhdGFiYXNlOiBwcm9wcy5nbHVlRGF0YWJhc2UucmVmLFxuICAgICAgcXVlcnlTdHJpbmc6IGBcbkNSRUFURSBPUiBSRVBMQUNFIFZJRVcgY2h1cm5fcHJlZGljdGlvbiBBU1xuU0VMRUNUIFxuICBjdXN0b21lcl9pZCxcbiAgaGVhbHRoX3Njb3JlLFxuICBoZWFsdGhfc2VnbWVudCxcbiAgdG90YWxfcmV2ZW51ZSxcbiAgQ0FTRSBcbiAgICBXSEVOIGhlYWx0aF9zY29yZSA8IDI1IFRIRU4gJ0NyaXRpY2FsIFJpc2snXG4gICAgV0hFTiBoZWFsdGhfc2NvcmUgPCAzMCBUSEVOICdIaWdoIFJpc2snXG4gICAgV0hFTiBoZWFsdGhfc2NvcmUgPCAzNSBUSEVOICdNZWRpdW0gUmlzaydcbiAgICBFTFNFICdMb3cgUmlzaydcbiAgRU5EIGFzIGNodXJuX3Jpc2ssXG4gIENBU0UgXG4gICAgV0hFTiBoZWFsdGhfc2NvcmUgPCAyNSBUSEVOIDAuNzBcbiAgICBXSEVOIGhlYWx0aF9zY29yZSA8IDMwIFRIRU4gMC40NVxuICAgIFdIRU4gaGVhbHRoX3Njb3JlIDwgMzUgVEhFTiAwLjIwXG4gICAgRUxTRSAwLjA1XG4gIEVORCBhcyBjaHVybl9wcm9iYWJpbGl0eSxcbiAgQ0FTRSBXSEVOIGhlYWx0aF9zY29yZSA8IDM1IFRIRU4gMSBFTFNFIDAgRU5EIGFzIGNodXJuX2luZGljYXRvcixcbiAgdG90YWxfcmV2ZW51ZSAqIENBU0UgXG4gICAgV0hFTiBoZWFsdGhfc2NvcmUgPCAyNSBUSEVOIDAuNzBcbiAgICBXSEVOIGhlYWx0aF9zY29yZSA8IDMwIFRIRU4gMC40NVxuICAgIFdIRU4gaGVhbHRoX3Njb3JlIDwgMzUgVEhFTiAwLjIwXG4gICAgRUxTRSAwLjA1XG4gIEVORCBhcyBleHBlY3RlZF9sb3NzXG5GUk9NIGN1c3RvbWVyX2hlYWx0aFxuV0hFUkUgaGVhbHRoX3Njb3JlIDwgMzVcbiAgICAgIGAsXG4gICAgICBuYW1lOiAnY2h1cm5fcHJlZGljdGlvbl92aWV3JyxcbiAgICAgIHdvcmtHcm91cDogdGhpcy53b3JrZ3JvdXAubmFtZSxcbiAgICB9KTtcbiAgICBjaHVyblByZWRpY3Rpb25WaWV3LmFkZERlcGVuZGVuY3kodGhpcy53b3JrZ3JvdXApO1xuXG4gICAgLy8gQ0xWIEFuYWx5c2lzIFZpZXdcbiAgICBjb25zdCBjbHZBbmFseXNpc1ZpZXcgPSBuZXcgYXRoZW5hLkNmbk5hbWVkUXVlcnkodGhpcywgJ0NMVkFuYWx5c2lzVmlldycsIHtcbiAgICAgIGRhdGFiYXNlOiBwcm9wcy5nbHVlRGF0YWJhc2UucmVmLFxuICAgICAgcXVlcnlTdHJpbmc6IGBcbkNSRUFURSBPUiBSRVBMQUNFIFZJRVcgY2x2X2FuYWx5c2lzIEFTXG5TRUxFQ1QgXG4gIGN1c3RvbWVyX2lkLFxuICB0b3RhbF9yZXZlbnVlICogMy41IGFzIGFjdHVhbF9jbHYsXG4gIHRvdGFsX3JldmVudWUgYXMgYW5udWFsX3ZhbHVlLFxuICB0b3RhbF9yZXZlbnVlICogNC4yIGFzIHByZWRpY3RlZF9jbHZfM3lyLFxuICBoZWFsdGhfc2NvcmUsXG4gIGhlYWx0aF9zZWdtZW50LFxuICB0b3RhbF9yZXZlbnVlLFxuICBDQVNFIFxuICAgIFdIRU4gdG90YWxfcmV2ZW51ZSA+PSAxMDAwMCBUSEVOICdCMkIgRmxlZXQnXG4gICAgV0hFTiB0b3RhbF9yZXZlbnVlID49IDQwMDAgVEhFTiAnQjJDIFByZW1pdW0nXG4gICAgV0hFTiB0b3RhbF9yZXZlbnVlID49IDIwMDAgVEhFTiAnQjJDIFN0YW5kYXJkJ1xuICAgIEVMU0UgJ0IyQyBFbnRyeSdcbiAgRU5EIGFzIGN1c3RvbWVyX3R5cGUsXG4gIENBU0UgXG4gICAgV0hFTiB0b3RhbF9yZXZlbnVlID49IDEwMDAwIFRIRU4gJ0VudGVycHJpc2UnXG4gICAgV0hFTiB0b3RhbF9yZXZlbnVlID49IDQwMDAgVEhFTiAnUHJlbWl1bSdcbiAgICBXSEVOIHRvdGFsX3JldmVudWUgPj0gMjAwMCBUSEVOICdTdGFuZGFyZCdcbiAgICBFTFNFICdFbnRyeSdcbiAgRU5EIGFzIHZhbHVlX3RpZXJcbkZST00gY3VzdG9tZXJfaGVhbHRoXG4gICAgICBgLFxuICAgICAgbmFtZTogJ2Nsdl9hbmFseXNpc192aWV3JyxcbiAgICAgIHdvcmtHcm91cDogdGhpcy53b3JrZ3JvdXAubmFtZSxcbiAgICB9KTtcbiAgICBjbHZBbmFseXNpc1ZpZXcuYWRkRGVwZW5kZW5jeSh0aGlzLndvcmtncm91cCk7XG5cbiAgICAvLyBSZXZlbnVlIGF0IFJpc2sgVmlld1xuICAgIGNvbnN0IHJldmVudWVBdFJpc2tWaWV3ID0gbmV3IGF0aGVuYS5DZm5OYW1lZFF1ZXJ5KHRoaXMsICdSZXZlbnVlQXRSaXNrVmlldycsIHtcbiAgICAgIGRhdGFiYXNlOiBwcm9wcy5nbHVlRGF0YWJhc2UucmVmLFxuICAgICAgcXVlcnlTdHJpbmc6IGBcbkNSRUFURSBPUiBSRVBMQUNFIFZJRVcgcmV2ZW51ZV9hdF9yaXNrIEFTXG5TRUxFQ1QgXG4gIGhlYWx0aF9zZWdtZW50LFxuICBDT1VOVCgqKSBhcyBjdXN0b21lcl9jb3VudCxcbiAgU1VNKHRvdGFsX3JldmVudWUpIGFzIHRvdGFsX3JldmVudWUsXG4gIFNVTShDQVNFIFdIRU4gaGVhbHRoX3Njb3JlIDwgNDAgVEhFTiB0b3RhbF9yZXZlbnVlIEVMU0UgMCBFTkQpIGFzIHJldmVudWVfYXRfcmlzayxcbiAgUk9VTkQoXG4gICAgU1VNKENBU0UgV0hFTiBoZWFsdGhfc2NvcmUgPCA0MCBUSEVOIHRvdGFsX3JldmVudWUgRUxTRSAwIEVORCkgKiAxMDAuMCAvIFxuICAgIE5VTExJRihTVU0odG90YWxfcmV2ZW51ZSksIDApLCAyXG4gICkgYXMgcGN0X2F0X3Jpc2tcbkZST00gY3VzdG9tZXJfaGVhbHRoXG5HUk9VUCBCWSBoZWFsdGhfc2VnbWVudFxuICAgICAgYCxcbiAgICAgIG5hbWU6ICdyZXZlbnVlX2F0X3Jpc2tfdmlldycsXG4gICAgICB3b3JrR3JvdXA6IHRoaXMud29ya2dyb3VwLm5hbWUsXG4gICAgfSk7XG4gICAgcmV2ZW51ZUF0Umlza1ZpZXcuYWRkRGVwZW5kZW5jeSh0aGlzLndvcmtncm91cCk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnQXRoZW5hV29ya2dyb3VwJywge1xuICAgICAgdmFsdWU6IHRoaXMud29ya2dyb3VwLm5hbWUhLFxuICAgICAgZGVzY3JpcHRpb246ICdBdGhlbmEgV29ya2dyb3VwIE5hbWUnLFxuICAgIH0pO1xuICB9XG59XG4iXX0=